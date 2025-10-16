import os
import asyncpg
import secrets
from fastapi import FastAPI, Request, Depends, HTTPException, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware
import httpx
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from web.object_storage import ObjectStorageService

# Initialize FastAPI app
app = FastAPI(title="DeckForge Admin Portal")

# Add session middleware for OAuth with proper cookie settings for iframe
app.add_middleware(
    SessionMiddleware, 
    secret_key=os.getenv("SESSION_SECRET", "your-secret-key-change-in-production"),
    same_site="none",  # Required for iframe/webview context
    https_only=True    # Required when using SameSite=None
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="web/static"), name="static")
templates = Jinja2Templates(directory="web/templates")

# Discord OAuth2 configuration
oauth = OAuth()
oauth.register(
    name='discord',
    client_id=os.getenv('DISCORD_CLIENT_ID'),
    client_secret=os.getenv('DISCORD_CLIENT_SECRET'),
    authorize_url='https://discord.com/api/oauth2/authorize',
    authorize_params=None,
    access_token_url='https://discord.com/api/oauth2/token',
    access_token_params=None,
    refresh_token_url=None,
    redirect_uri=os.getenv('DISCORD_REDIRECT_URI', 'http://localhost:5000/auth/callback'),
    client_kwargs={'scope': 'identify guilds'},
)

# Database connection pool
db_pool: Optional[asyncpg.Pool] = None

async def get_db_pool():
    """Get database connection pool"""
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(
            os.getenv("DATABASE_URL"),
            min_size=2,
            max_size=10,
            command_timeout=60
        )
    return db_pool

# Helper: Get current user from session cookie + database
async def get_current_user(request: Request) -> Optional[Dict]:
    """Get current authenticated user from session"""
    session_id = request.cookies.get('session_id')
    if not session_id:
        return None
    
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        session = await conn.fetchrow(
            "SELECT * FROM user_sessions WHERE session_id = $1 AND expires_at > NOW()",
            session_id
        )
        if session:
            return {
                'id': session['user_id'],
                'username': session['username'],
                'discriminator': session['discriminator'],
                'avatar': session['avatar'],
                'access_token': session['access_token']
            }
    return None

# Helper: Check if user is global admin
def is_global_admin(user_id: int) -> bool:
    """Check if user is a global admin"""
    admin_ids_str = os.getenv("ADMIN_IDS", "")
    if not admin_ids_str:
        return False
    admin_ids = [int(id.strip()) for id in admin_ids_str.split(",") if id.strip()]
    return user_id in admin_ids

# Helper: Get user's managed guilds from Discord API
async def get_user_managed_guilds(access_token: str) -> List[Dict]:
    """Fetch guilds where user has MANAGE_SERVER permission"""
    async with httpx.AsyncClient() as client:
        headers = {'Authorization': f'Bearer {access_token}'}
        response = await client.get('https://discord.com/api/users/@me/guilds', headers=headers)
        
        if response.status_code != 200:
            return []
        
        guilds = response.json()
        # Filter for guilds where user has MANAGE_GUILD permission (0x20)
        managed_guilds = [
            guild for guild in guilds
            if int(guild.get('permissions', 0)) & 0x20
        ]
        return managed_guilds

# Dependency: Require authentication
async def require_auth(request: Request):
    """Dependency to require authentication"""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

# Dependency: Require admin access
async def require_admin(request: Request, user = Depends(require_auth)):
    """Dependency to require admin access"""
    if not is_global_admin(user['id']):
        # Check if user manages any servers
        managed_guilds = await get_user_managed_guilds(user.get('access_token', ''))
        if not managed_guilds:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
    return user

@app.on_event("startup")
async def startup():
    """Initialize database pool on startup"""
    await get_db_pool()

@app.on_event("shutdown")
async def shutdown():
    """Close database pool on shutdown"""
    global db_pool
    if db_pool:
        await db_pool.close()

# Routes
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page / login page"""
    user = await get_current_user(request)
    if user:
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/login")
async def login(request: Request):
    """Initiate Discord OAuth2 login with database-backed state"""
    # Generate a unique state token
    state = secrets.token_urlsafe(32)
    
    # Store state in database
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO oauth_states (state) VALUES ($1)",
            state
        )
    
    # Build Discord OAuth URL with our state
    redirect_uri = os.getenv('DISCORD_REDIRECT_URI')
    client_id = os.getenv('DISCORD_CLIENT_ID')
    oauth_url = (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code"
        f"&scope=identify%20guilds"
        f"&state={state}"
    )
    
    return RedirectResponse(url=oauth_url)

@app.get("/auth/callback")
async def auth_callback(request: Request):
    """OAuth2 callback handler with database-backed state verification"""
    try:
        # Get state and code from query params
        state = request.query_params.get('state')
        code = request.query_params.get('code')
        
        if not state or not code:
            return RedirectResponse(url="/?error=auth_failed")
        
        # Verify state from database
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            state_record = await conn.fetchrow(
                "SELECT * FROM oauth_states WHERE state = $1 AND expires_at > NOW()",
                state
            )
            
            if not state_record:
                print("OAuth error: Invalid or expired state")
                return RedirectResponse(url="/?error=auth_failed")
            
            # Delete used state
            await conn.execute("DELETE FROM oauth_states WHERE state = $1", state)
        
        # Exchange code for token
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                'https://discord.com/api/oauth2/token',
                data={
                    'client_id': os.getenv('DISCORD_CLIENT_ID'),
                    'client_secret': os.getenv('DISCORD_CLIENT_SECRET'),
                    'grant_type': 'authorization_code',
                    'code': code,
                    'redirect_uri': os.getenv('DISCORD_REDIRECT_URI'),
                },
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            if token_response.status_code != 200:
                print(f"Token exchange failed: {token_response.text}")
                return RedirectResponse(url="/?error=auth_failed")
            
            token_data = token_response.json()
            access_token = token_data['access_token']
            
            # Fetch user info
            headers = {'Authorization': f'Bearer {access_token}'}
            user_response = await client.get('https://discord.com/api/users/@me', headers=headers)
            
            if user_response.status_code != 200:
                print(f"User fetch failed: {user_response.text}")
                return RedirectResponse(url="/?error=auth_failed")
            
            user_data = user_response.json()
        
        # Create session in database
        session_id = secrets.token_urlsafe(32)
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO user_sessions 
                   (session_id, user_id, username, discriminator, avatar, access_token)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                session_id,
                int(user_data['id']),
                user_data['username'],
                user_data.get('discriminator', '0'),
                user_data.get('avatar'),
                access_token
            )
        
        # Set session cookie and redirect
        response = RedirectResponse(url="/dashboard")
        response.set_cookie(
            key="session_id",
            value=session_id,
            max_age=7*24*60*60,  # 7 days
            httponly=True,
            secure=True,
            samesite="none"
        )
        return response
        
    except Exception as e:
        print(f"OAuth error: {e}")
        import traceback
        traceback.print_exc()
        return RedirectResponse(url="/?error=auth_failed")

@app.get("/logout")
async def logout(request: Request):
    """Logout user"""
    session_id = request.cookies.get('session_id')
    if session_id:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM user_sessions WHERE session_id = $1", session_id)
    
    response = RedirectResponse(url="/")
    response.delete_cookie(key="session_id")
    return response

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user = Depends(require_admin)):
    """Main dashboard showing user's managed servers and decks"""
    pool = await get_db_pool()
    
    # Get user's managed guilds
    managed_guilds = await get_user_managed_guilds(user.get('access_token', ''))
    
    # Get deck assignments for these guilds
    async with pool.acquire() as conn:
        # Get all decks created by this user
        user_decks = await conn.fetch(
            "SELECT * FROM decks WHERE created_by = $1 ORDER BY created_at DESC",
            user['id']
        )
        
        # If global admin, also show all decks
        if is_global_admin(user['id']):
            all_decks = await conn.fetch(
                "SELECT * FROM decks ORDER BY created_at DESC"
            )
        else:
            all_decks = user_decks
        
        # Get server-deck assignments
        guild_ids = [int(g['id']) for g in managed_guilds]
        server_decks = {}
        if guild_ids:
            assignments = await conn.fetch(
                "SELECT guild_id, deck_id FROM server_decks WHERE guild_id = ANY($1)",
                guild_ids
            )
            server_decks = {row['guild_id']: row['deck_id'] for row in assignments}
    
    # Combine guild info with deck assignments
    guilds_with_decks = []
    for guild in managed_guilds:
        guild_id = int(guild['id'])
        guilds_with_decks.append({
            'id': guild_id,
            'name': guild['name'],
            'icon': guild.get('icon'),
            'deck_id': server_decks.get(guild_id)
        })
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "guilds": guilds_with_decks,
        "decks": [dict(d) for d in all_decks],
        "is_global_admin": is_global_admin(user['id'])
    })

@app.post("/server/{guild_id}/assign-deck")
async def assign_deck_to_server(
    request: Request,
    guild_id: int,
    deck_id: int = Form(None),
    user = Depends(require_admin)
):
    """Assign a deck to a Discord server"""
    pool = await get_db_pool()
    
    # Verify user manages this server
    managed_guilds = await get_user_managed_guilds(user.get('access_token', ''))
    guild_ids = [int(g['id']) for g in managed_guilds]
    
    if guild_id not in guild_ids and not is_global_admin(user['id']):
        raise HTTPException(status_code=403, detail="You don't manage this server")
    
    async with pool.acquire() as conn:
        if deck_id:
            # Assign or update deck
            await conn.execute(
                """INSERT INTO server_decks (guild_id, deck_id)
                   VALUES ($1, $2)
                   ON CONFLICT (guild_id) DO UPDATE SET deck_id = $2""",
                guild_id, deck_id
            )
        else:
            # Remove deck assignment
            await conn.execute(
                "DELETE FROM server_decks WHERE guild_id = $1",
                guild_id
            )
    
    return RedirectResponse(url="/dashboard", status_code=303)

@app.post("/api/images/upload-url")
async def get_image_upload_url(request: Request, user = Depends(require_admin)):
    """Get a presigned URL for uploading an image"""
    file_extension = request.query_params.get("extension", "")
    
    try:
        storage = ObjectStorageService()
        upload_url = await storage.get_upload_url(file_extension)
        return {"uploadUrl": upload_url}
    except ValueError as e:
        # PRIVATE_OBJECT_DIR not set
        raise HTTPException(
            status_code=500, 
            detail=str(e)
        )
    except Exception as e:
        # Other storage errors
        raise HTTPException(
            status_code=500,
            detail=f"Image upload not configured: {str(e)}"
        )

@app.post("/api/images/confirm")
async def confirm_image_upload(
    request: Request,
    upload_url: str = Form(...),
    user = Depends(require_admin)
):
    """Confirm image upload and return the image path for database storage"""
    try:
        storage = ObjectStorageService()
        image_path = storage.get_image_path(upload_url)
        return {"imagePath": image_path}
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image confirmation failed: {str(e)}")

@app.get("/images/card-images/{image_id:path}")
async def serve_card_image(image_id: str):
    """Serve uploaded card images from object storage"""
    try:
        storage = ObjectStorageService()
        image_path = f"/images/card-images/{image_id}"
        
        signed_url = await storage.get_image_url(image_path)
        if not signed_url:
            raise HTTPException(status_code=404, detail="Image not found")
        
        # Redirect to the signed URL
        return RedirectResponse(url=signed_url)
    except ValueError:
        # PRIVATE_OBJECT_DIR not set
        raise HTTPException(status_code=500, detail="Object storage not configured")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/deck/create", response_class=HTMLResponse)
async def create_deck_form(request: Request, user = Depends(require_admin)):
    """Show deck creation form"""
    return templates.TemplateResponse("create_deck.html", {
        "request": request,
        "user": user
    })

@app.post("/deck/create")
async def create_deck(
    request: Request,
    name: str = Form(...),
    free_pack_cooldown_hours: int = Form(...),
    user = Depends(require_admin)
):
    """Create a new deck with template fields"""
    # Validate cooldown
    if free_pack_cooldown_hours < 1 or free_pack_cooldown_hours > 168:
        raise HTTPException(status_code=400, detail="Cooldown must be between 1 and 168 hours")
    
    pool = await get_db_pool()
    form_data = await request.form()
    
    async with pool.acquire() as conn:
        # Create deck with cooldown
        deck = await conn.fetchrow(
            """INSERT INTO decks (name, created_by, free_pack_cooldown_hours)
               VALUES ($1, $2, $3)
               RETURNING deck_id, name""",
            name, user['id'], free_pack_cooldown_hours
        )
        
        # Create default rarity ranges (7-tier system)
        default_rates = {
            'Common': 40.0,
            'Uncommon': 25.0,
            'Exceptional': 15.0,
            'Rare': 10.0,
            'Epic': 6.0,
            'Legendary': 3.0,
            'Mythic': 1.0
        }
        
        for rarity, rate in default_rates.items():
            await conn.execute(
                """INSERT INTO rarity_ranges (deck_id, rarity, drop_rate)
                   VALUES ($1, $2, $3)""",
                deck['deck_id'], rarity, rate
            )
        
        # Create template fields if provided
        field_names = form_data.getlist('field_names[]')
        field_types = form_data.getlist('field_types[]')
        dropdown_options = form_data.getlist('dropdown_options[]')
        is_required = form_data.getlist('is_required[]')
        
        for idx, field_name in enumerate(field_names):
            if field_name:  # Skip empty names
                field_type = field_types[idx] if idx < len(field_types) else 'text'
                options = dropdown_options[idx] if idx < len(dropdown_options) else None
                # is_required[] contains '1' for required, '0' for not required
                required = is_required[idx] == '1' if idx < len(is_required) else False
                
                await conn.execute(
                    """INSERT INTO card_templates 
                       (deck_id, field_name, field_type, dropdown_options, field_order, is_required)
                       VALUES ($1, $2, $3, $4, $5, $6)""",
                    deck['deck_id'], field_name, field_type, options, idx, required
                )
    
    return RedirectResponse(url=f"/deck/{deck['deck_id']}/edit", status_code=303)

@app.get("/deck/{deck_id}/edit", response_class=HTMLResponse)
async def edit_deck_form(request: Request, deck_id: int, user = Depends(require_admin)):
    """Show deck editing form (manage cards)"""
    pool = await get_db_pool()
    
    async with pool.acquire() as conn:
        # Get deck info
        deck = await conn.fetchrow(
            "SELECT * FROM decks WHERE deck_id = $1",
            deck_id
        )
        
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")
        
        # Check permissions
        if deck['created_by'] != user['id'] and not is_global_admin(user['id']):
            raise HTTPException(status_code=403, detail="You don't own this deck")
        
        # Get template fields for this deck
        template_fields = await conn.fetch(
            """SELECT * FROM card_templates 
               WHERE deck_id = $1 
               ORDER BY field_order""",
            deck_id
        )
        
        # Get cards in this deck with their template field values
        cards = await conn.fetch(
            """SELECT c.*, 
                      array_agg(json_build_object(
                          'template_id', ctf.template_id,
                          'field_value', ctf.field_value
                      ) ORDER BY ct.field_order) FILTER (WHERE ctf.field_id IS NOT NULL) as template_values
               FROM cards c
               LEFT JOIN card_template_fields ctf ON c.card_id = ctf.card_id
               LEFT JOIN card_templates ct ON ctf.template_id = ct.template_id
               WHERE c.deck_id = $1 
               GROUP BY c.card_id
               ORDER BY c.rarity, c.name""",
            deck_id
        )
    
    return templates.TemplateResponse("edit_deck.html", {
        "request": request,
        "user": user,
        "template_fields": template_fields,
        "deck": dict(deck),
        "cards": [dict(c) for c in cards]
    })

@app.post("/deck/{deck_id}/card/add")
async def add_card_to_deck(
    request: Request,
    deck_id: int,
    name: str = Form(...),
    description: str = Form(...),
    rarity: str = Form(...),
    image_url: str = Form(None),
    user = Depends(require_admin)
):
    """Add a card to a deck with template field values"""
    pool = await get_db_pool()
    form_data = await request.form()
    
    async with pool.acquire() as conn:
        # Verify deck ownership
        deck = await conn.fetchrow(
            "SELECT created_by FROM decks WHERE deck_id = $1",
            deck_id
        )
        
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")
        
        if deck['created_by'] != user['id'] and not is_global_admin(user['id']):
            raise HTTPException(status_code=403, detail="You don't own this deck")
        
        # Insert card with basic fields only
        card = await conn.fetchrow(
            """INSERT INTO cards (deck_id, name, description, rarity, image_url, created_by)
               VALUES ($1, $2, $3, $4, $5, $6)
               RETURNING card_id""",
            deck_id, name, description, rarity, image_url, user['id']
        )
        
        # Get template fields for this deck
        template_fields = await conn.fetch(
            "SELECT template_id FROM card_templates WHERE deck_id = $1",
            deck_id
        )
        
        # Insert template field values
        for template_field in template_fields:
            template_id = template_field['template_id']
            field_key = f"template_field_{template_id}"
            
            if field_key in form_data:
                field_value = form_data.get(field_key)
                if field_value:  # Only insert non-empty values
                    await conn.execute(
                        """INSERT INTO card_template_fields (card_id, template_id, field_value)
                           VALUES ($1, $2, $3)""",
                        card['card_id'], template_id, field_value
                    )
    
    return RedirectResponse(url=f"/deck/{deck_id}/edit", status_code=303)

@app.post("/deck/{deck_id}/card/{card_id}/delete")
async def delete_card_from_deck(
    request: Request,
    deck_id: int,
    card_id: int,
    user = Depends(require_admin)
):
    """Delete a card from a deck"""
    pool = await get_db_pool()
    
    async with pool.acquire() as conn:
        # Verify deck ownership
        deck = await conn.fetchrow(
            "SELECT created_by FROM decks WHERE deck_id = $1",
            deck_id
        )
        
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")
        
        if deck['created_by'] != user['id'] and not is_global_admin(user['id']):
            raise HTTPException(status_code=403, detail="You don't own this deck")
        
        # Delete card
        await conn.execute(
            "DELETE FROM cards WHERE card_id = $1 AND deck_id = $2",
            card_id, deck_id
        )
    
    return RedirectResponse(url=f"/deck/{deck_id}/edit", status_code=303)

@app.get("/deck/{deck_id}/cooldown", response_class=HTMLResponse)
async def edit_cooldown(request: Request, deck_id: int, user = Depends(require_admin)):
    """Show cooldown editor"""
    pool = await get_db_pool()
    
    async with pool.acquire() as conn:
        # Get deck info
        deck = await conn.fetchrow(
            "SELECT * FROM decks WHERE deck_id = $1",
            deck_id
        )
        
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")
        
        # Check permissions
        if deck['created_by'] != user['id'] and not is_global_admin(user['id']):
            raise HTTPException(status_code=403, detail="You don't own this deck")
    
    return templates.TemplateResponse("edit_cooldown.html", {
        "request": request,
        "user": user,
        "deck": dict(deck)
    })

@app.post("/deck/{deck_id}/cooldown/update")
async def update_cooldown(
    request: Request,
    deck_id: int,
    free_pack_cooldown_hours: int = Form(...),
    user = Depends(require_admin)
):
    """Update deck cooldown"""
    # Validate cooldown
    if free_pack_cooldown_hours < 1 or free_pack_cooldown_hours > 168:
        raise HTTPException(status_code=400, detail="Cooldown must be between 1 and 168 hours")
    
    pool = await get_db_pool()
    
    async with pool.acquire() as conn:
        # Verify deck ownership
        deck = await conn.fetchrow(
            "SELECT created_by FROM decks WHERE deck_id = $1",
            deck_id
        )
        
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")
        
        if deck['created_by'] != user['id'] and not is_global_admin(user['id']):
            raise HTTPException(status_code=403, detail="You don't own this deck")
        
        # Update cooldown
        await conn.execute(
            "UPDATE decks SET free_pack_cooldown_hours = $1 WHERE deck_id = $2",
            free_pack_cooldown_hours, deck_id
        )
    
    return RedirectResponse(url=f"/deck/{deck_id}/edit", status_code=303)

@app.get("/deck/{deck_id}/rarity", response_class=HTMLResponse)
async def edit_rarity_rates(request: Request, deck_id: int, user = Depends(require_admin)):
    """Show rarity rate editor"""
    pool = await get_db_pool()
    
    async with pool.acquire() as conn:
        # Get deck info
        deck = await conn.fetchrow(
            "SELECT * FROM decks WHERE deck_id = $1",
            deck_id
        )
        
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")
        
        # Check permissions
        if deck['created_by'] != user['id'] and not is_global_admin(user['id']):
            raise HTTPException(status_code=403, detail="You don't own this deck")
        
        # Get rarity rates
        rates = await conn.fetch(
            "SELECT * FROM rarity_ranges WHERE deck_id = $1 ORDER BY rarity",
            deck_id
        )
    
    return templates.TemplateResponse("edit_rarity.html", {
        "request": request,
        "user": user,
        "deck": dict(deck),
        "rates": [dict(r) for r in rates]
    })

@app.post("/deck/{deck_id}/rarity/update")
async def update_rarity_rates(
    request: Request,
    deck_id: int,
    user = Depends(require_admin)
):
    """Update rarity rates for a deck"""
    pool = await get_db_pool()
    form_data = await request.form()
    
    # Parse rates from form
    rates = {}
    for key, value in form_data.items():
        if key.startswith('rate_'):
            rarity = key.replace('rate_', '')
            try:
                rates[rarity] = float(value)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid rate for {rarity}")
    
    # Validate total = 100
    total = sum(rates.values())
    if abs(total - 100.0) > 0.01:
        raise HTTPException(status_code=400, detail=f"Rates must total 100% (current: {total}%)")
    
    async with pool.acquire() as conn:
        # Verify deck ownership
        deck = await conn.fetchrow(
            "SELECT created_by FROM decks WHERE deck_id = $1",
            deck_id
        )
        
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")
        
        if deck['created_by'] != user['id'] and not is_global_admin(user['id']):
            raise HTTPException(status_code=403, detail="You don't own this deck")
        
        # Update rates
        async with conn.transaction():
            for rarity, rate in rates.items():
                await conn.execute(
                    """INSERT INTO rarity_ranges (deck_id, rarity, drop_rate)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (deck_id, rarity) 
                       DO UPDATE SET drop_rate = $3""",
                    deck_id, rarity, rate
                )
    
    return RedirectResponse(url=f"/deck/{deck_id}/rarity?success=1", status_code=303)

# Health check endpoint
@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "ok", "service": "DeckForge Admin Portal"}
