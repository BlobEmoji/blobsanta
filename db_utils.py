import asyncpg


async def fetch_gift_nickname(conn: asyncpg.pool.PoolConnectionProxy, user_id: int) -> str:
    nickname = await conn.fetchval("""
        SELECT nickname
        FROM gifts 
        INNER JOIN user_data
        ON target_user_id = user_data.user_id
        WHERE gifts.user_id = $1 AND active 
        """, user_id)
    return nickname


async def last_gift_from_db(conn: asyncpg.pool.PoolConnectionProxy, user_id: int):
    last_gift = await conn.fetchval("""
    SELECT last_gift
    FROM user_data
    WHERE user_id = $1
    """, user_id)
    return last_gift


async def check_has_gift(db, author_id: int) -> bool:
    async with db.acquire() as conn:
        check = await conn.fetchval("""
        SELECT EXISTS (
        SELECT 1
        FROM gifts
        WHERE active = TRUE and user_id = $1
        )
        """, author_id)
    return check


async def check_is_in(conn: asyncpg.pool.PoolConnectionProxy, user_id: int) -> bool:
    check = await conn.fetchval("""
    SELECT EXISTS (
        SELECT 1
        FROM user_data
        WHERE user_id = $1
    )
    """, user_id)
    return check
