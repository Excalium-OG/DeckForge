# main.py — updated with Marketplace, set-public, and adopt endpoints
import os
import asyncio
import asyncpg
import secrets
from fastapi import FastAPI, Request, Depends, HTTPException, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from authlib.integrations.starlette_client import OAuth
from starlette.middleware.sessions import SessionMiddleware
import httpx
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from web.object_storage import ObjectStorageService
from fastapi.staticfiles import StaticFiles as BaseStaticFiles

# Initialize FastAPI app
app = FastAPI(title="DeckForge Admin Portal")

# Add session middleware for OAuth with proper cookie settings for iframe
app.add_middleware(
    SessionMiddleware, 
    secret_key=os.getenv("SESSION_SECRET", "your-secret-key-change-in-production"),
    same_site="none",  # Required for iframe/webview context
    https_only=True    # Required when using SameSite=None
)

# Mount static files and templates with no-cache headers


class NoCacheStaticFiles(BaseStaticFiles):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    async def __call__(self, scope, receive, send):
        async def send_wrapper(message):
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                # Add no-cache headers
                headers.append((b'cache-control', b'no-store, no-cache, must-revalidate, max-age=0'))
                headers.append((b'pragma', b'no-cache'))
                headers.append((b'expires', b'0'))
                message['headers'] = headers
            await send(message)
        await super().__call__(scope, receive, send_wrapper)

app.mount("/static", NoCacheStaticFiles(directory="web/static"), name="static")
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
    if not access_token:
        return []
    
    async with httpx.AsyncClient() as client:
        headers = {'Authorization': f'Bearer {access_token}'}
        
        try:
            response = await client.get('https://discord.com/api/users/@me/guilds', headers=headers, timeout=10.0)
            
            if response.status_code == 429:
                # Rate limited - wait and retry once
                retry_after = response.json().get('retry_after', 1)
                await asyncio.sleep(retry_after)
                response = await client.get('https://discord.com/api/users/@me/guilds', headers=headers, timeout=10.0)
            
            if response.status_code != 200:
                print(f"Discord API error: {response.status_code} - {response.text}")
                return []
            
            guilds = response.json()
            # Filter for guilds where user has MANAGE_GUILD permission (0x20)
            managed_guilds = [
                guild for guild in guilds
                if int(guild.get('permissions', 0)) & 0x20
            ]
            return managed_guilds
        except Exception as e:
            print(f"Error fetching guilds: {e}")
            return []

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

# Marketplace: list public decks
@app.get("/marketplace", response_class=HTMLResponse)
async def marketplace(request: Request, user = Depends(require_auth)):
    """Show public decks available for adoption"""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT deck_id, name, created_by, created_at, public_description FROM decks WHERE is_public = TRUE ORDER BY created_at DESC"
        )
    decks = [dict(r) for r in rows]

    # Also pass the user's managed guilds so the template can populate adopt select
    managed_guilds = await get_user_managed_guilds(user.get('access_token', ''))
    return templates.TemplateResponse("marketplace.html", {
        "request": request,
        "user": user,
        "decks": decks,
        "managed_guilds": managed_guilds
    })

# Endpoint for deck owner to set public flag and description
@app.post("/deck/{deck_id}/set-public")
async def set_deck_public(request: Request, deck_id: int, is_public: int = Form(0), public_description: str = Form(""), user = Depends(require_admin)):
    """Toggle public visibility for a deck (owner or global admin only)"""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        deck = await conn.fetchrow("SELECT created_by FROM decks WHERE deck_id = $1", deck_id)
        if not deck:
            raise HTTPException(status_code=404, detail="Deck not found")
        if deck['created_by'] != user['id'] and not is_global_admin(user['id']):
            raise HTTPException(status_code=403, detail="You don't own this deck")
        await conn.execute(
            "UPDATE decks SET is_public = $1, public_description = $2 WHERE deck_id = $3",
            bool(is_public), public_description or None, deck_id
        )
    return RedirectResponse(url=f"/deck/{deck_id}/edit", status_code=303)

# Adopt (import) a public deck into a managed server (clones deck content and assigns)
@app.post("/marketplace/{deck_id}/adopt")
async def adopt_deck(deck_id: int, guild_id: int = Form(...), user = Depends(require_admin)):
    """
    Clone a public deck and assign it to the specified guild.
    The cloned deck is owned by the importing user (they can edit it).
    """
    # Verify user manages the target guild
    managed_guilds = await get_user_managed_guilds(user.get('access_token',''))
    guild_ids = [int(g['id']) for g in managed_guilds]
    if guild_id not in guild_ids and not is_global_admin(user['id']):
        raise HTTPException(status_code=403, detail="You don't manage this server")

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        public_deck = await conn.fetchrow(
            "SELECT * FROM decks WHERE deck_id = $1 AND is_public = TRUE",
            deck_id
        )
        if not public_deck:
            raise HTTPException(status_code=404, detail="Public deck not found")

        async with conn.transaction():
            # Create cloned deck owned by importer

            public_deck = dict(public_deck)

            new_deck = await conn.fetchrow(
                """INSERT INTO decks (name, created_by, free_pack_cooldown_hours)
                   VALUES ($1, $2, $3)
                   RETURNING deck_id""",
                public_deck['name'], user['id'], public_deck.get('free_pack_cooldown_hours', 24)
            )
            new_deck_id = new_deck['deck_id']

            # Copy rarity_ranges
            rates = await conn.fetch("SELECT rarity, drop_rate FROM rarity_ranges WHERE deck_id = $1", deck_id)
            for r in rates:
                await conn.execute(
                    "INSERT INTO rarity_ranges (deck_id, rarity, drop_rate) VALUES ($1, $2, $3)",
                    new_deck_id, r['rarity'], r['drop_rate']
                )

            # Copy card_templates and keep mapping (template_id_old -> template_id_new)
            templates_rows = await conn.fetch("SELECT template_id, field_name, field_type, dropdown_options, field_order, is_required FROM card_templates WHERE deck_id = $1", deck_id)
            template_map = {}
            for t in templates_rows:
                new_t = await conn.fetchrow(
                    """INSERT INTO card_templates (deck_id, field_name, field_type, dropdown_options, field_order, is_required)
                       VALUES ($1, $2, $3, $4, $5, $6) RETURNING template_id""",
                    new_deck_id, t['field_name'], t['field_type'], t['dropdown_options'], t['field_order'], t['is_required']
                )
                template_map[t['template_id']] = new_t['template_id']

            # Copy cards and their template field values (map to new template ids)
            cards = await conn.fetch("SELECT * FROM cards WHERE deck_id = $1", deck_id)
            for c in cards:
                new_card = await conn.fetchrow(
                    """INSERT INTO cards (deck_id, name, description, rarity, image_url, created_by)
                       VALUES ($1, $2, $3, $4, $5, $6) RETURNING card_id""",
                    new_deck_id, c['name'], c['description'], c['rarity'], c['image_url'], user['id']
                )
                new_card_id = new_card['card_id']

                # Copy template fields for this card
                card_fields = await conn.fetch("SELECT template_id, field_value FROM card_template_fields WHERE card_id = $1", c['card_id'])
                for cf in card_fields:
                    new_template_id = template_map.get(cf['template_id'])
                    if new_template_id:
                        await conn.execute(
                            "INSERT INTO card_template_fields (card_id, template_id, field_value) VALUES ($1, $2, $3)",
                            new_card_id, new_template_id, cf['field_value']
                        )

            # Assign deck to the selected guild
            await conn.execute(
                "INSERT INTO server_decks (guild_id, deck_id) VALUES ($1, $2) ON CONFLICT (guild_id) DO UPDATE SET deck_id = $2",
                guild_id, deck_id
            )

    return RedirectResponse(url="/dashboard", status_code=303)

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
        
        # Get number-type template fields for merge perks dropdown
        number_template_fields = await conn.fetch(
            """SELECT template_id, field_name FROM card_templates 
               WHERE deck_id = $1 AND field_type = 'number'
               ORDER BY field_name""",
            deck_id
        )
        
        # Get existing merge perks for this deck
        merge_perks = await conn.fetch(
            """SELECT perk_name, base_boost, diminishing_factor 
               FROM deck_merge_perks 
               WHERE deck_id = $1 
               ORDER BY perk_name""",
            deck_id
        )
        
        # Get cards in this deck with their template field values
        cards = await conn.fetch(
            """SELECT c.*, 
                      array_agg(json_build_object(
                          'template_id', ctf.template_id,
                          'field_value', ctf.field_value
                      ) ORDER BY ct.field_order) FILTER (WHERE ctf.template_id IS NOT NULL) as template_values
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
        "number_template_fields": number_template_fields,
        "merge_perks": merge_perks,
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
    mergeable: bool = Form(False),
    max_merge_level: int = Form(10),
    user = Depends(require_admin)
):
    """Add a card to a deck with template field values and merge configuration"""
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
        
        # Insert card with basic fields and merge configuration
        card = await conn.fetchrow(
            """INSERT INTO cards (deck_id, name, description, rarity, image_url, created_by, mergeable, max_merge_level)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
               RETURNING card_id""",
            deck_id, name, description, rarity, image_url, user['id'], mergeable, max_merge_level
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

@app.post("/deck/{deck_id}/merge_perk/add")
async def add_merge_perk(
    request: Request,
    deck_id: int,
    perk_name: str = Form(...),
    base_boost: float = Form(...),
    user = Depends(require_admin)
):
    """Add a merge perk to a deck"""
    pool = await get_db_pool()
    
    # Validate base_boost
    if base_boost < 0.1 or base_boost > 100:
        raise HTTPException(status_code=400, detail="Base boost must be between 0.1 and 100")
    
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
        
        # Insert merge perk (using default diminishing_factor of 0.85)
        try:
            await conn.execute(
                """INSERT INTO deck_merge_perks (deck_id, perk_name, base_boost, diminishing_factor)
                   VALUES ($1, $2, $3, 0.85)""",
                deck_id, perk_name, base_boost
            )
        except Exception as e:
            # Handle duplicate perk name
            if 'duplicate key' in str(e).lower():
                raise HTTPException(status_code=400, detail=f"Merge perk '{perk_name}' already exists for this deck")
            raise
    
    return RedirectResponse(url=f"/deck/{deck_id}/edit", status_code=303)

@app.post("/deck/{deck_id}/merge_perk/{perk_name}/delete")
async def delete_merge_perk(
    request: Request,
    deck_id: int,
    perk_name: str,
    user = Depends(require_admin)
):
    """Delete a merge perk from a deck"""
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
        
        # Delete merge perk
        await conn.execute(
            "DELETE FROM deck_merge_perks WHERE deck_id = $1 AND perk_name = $2",
            deck_id, perk_name
        )
    
    return RedirectResponse(url=f"/deck/{deck_id}/edit", status_code=303)

@app.get("/deck/{deck_id}/card/{card_id}/edit", response_class=HTMLResponse)
async def edit_card_form(request: Request, deck_id: int, card_id: int, user = Depends(require_admin)):
    """Show card editing form"""
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
        
        # Get card info
        card = await conn.fetchrow(
            "SELECT * FROM cards WHERE card_id = $1 AND deck_id = $2",
            card_id, deck_id
        )
        
        if not card:
            raise HTTPException(status_code=404, detail="Card not found")
        
        # Get template fields for this deck
        template_fields = await conn.fetch(
            """SELECT * FROM card_templates 
               WHERE deck_id = $1 
               ORDER BY field_order""",
            deck_id
        )
        
        # Get existing field values for this card
        field_values_rows = await conn.fetch(
            """SELECT template_id, field_value 
               FROM card_template_fields 
               WHERE card_id = $1""",
            card_id
        )
        
        # Convert to dictionary for easy lookup
        field_values = {row['template_id']: row['field_value'] for row in field_values_rows}
    
    return templates.TemplateResponse("edit_card.html", {
        "request": request,
        "user": user,
        "deck": dict(deck),
        "card": dict(card),
        "template_fields": template_fields,
        "field_values": field_values
    })

@app.post("/deck/{deck_id}/card/{card_id}/update")
async def update_card(
    request: Request,
    deck_id: int,
    card_id: int,
    name: str = Form(...),
    description: str = Form(...),
    rarity: str = Form(...),
    image_url: str = Form(None),
    mergeable: bool = Form(False),
    max_merge_level: int = Form(0),
    user = Depends(require_admin)
):
    """Update an existing card with all editable attributes"""
    pool = await get_db_pool()
    form_data = await request.form()
    
    # If not mergeable, set max_merge_level to 0
    if not mergeable:
        max_merge_level = 0
    
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
        
        # Verify card belongs to this deck
        card = await conn.fetchrow(
            "SELECT card_id FROM cards WHERE card_id = $1 AND deck_id = $2",
            card_id, deck_id
        )
        
        if not card:
            raise HTTPException(status_code=404, detail="Card not found in this deck")
        
        # Normalize blank image_url to NULL
        if image_url == '':
            image_url = None
        
        # Use transaction to ensure atomicity
        async with conn.transaction():
            # Update card basic fields
            await conn.execute(
                """UPDATE cards 
                   SET name = $1, description = $2, rarity = $3, image_url = $4, 
                       mergeable = $5, max_merge_level = $6
                   WHERE card_id = $7""",
                name, description, rarity, image_url, mergeable, max_merge_level, card_id
            )
            
            # Get template fields for this deck
            template_fields = await conn.fetch(
                "SELECT template_id FROM card_templates WHERE deck_id = $1",
                deck_id
            )
            
            # Update template field values
            for template_field in template_fields:
                template_id = template_field['template_id']
                field_key = f"template_field_{template_id}"
                
                if field_key in form_data:
                    field_value = form_data.get(field_key)
                    
                    # Check if value already exists
                    existing = await conn.fetchrow(
                        """SELECT field_value FROM card_template_fields 
                           WHERE card_id = $1 AND template_id = $2""",
                        card_id, template_id
                    )
                    
                    if field_value:  # Update or insert non-empty values
                        if existing:
                            await conn.execute(
                                """UPDATE card_template_fields 
                                   SET field_value = $1 
                                   WHERE card_id = $2 AND template_id = $3""",
                                field_value, card_id, template_id
                            )
                        else:
                            await conn.execute(
                                """INSERT INTO card_template_fields (card_id, template_id, field_value)
                                   VALUES ($1, $2, $3)""",
                                card_id, template_id, field_value
                            )
                    elif existing:  # Delete empty values
                        await conn.execute(
                            """DELETE FROM card_template_fields 
                               WHERE card_id = $1 AND template_id = $2""",
                            card_id, template_id
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

import uvicorn

if __name__ == "__main__":
    # port = int(os.environ.get("PORT", 8000))  # Railway injects this
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

@app.get("/ping")
def ping():
    return {"status": "ok"}
