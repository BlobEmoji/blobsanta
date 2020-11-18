from discord.ext import commands


def test_username(nickname: str, ctx: commands.Context) -> list:
    errors = []
    string_to_test = ctx.author.display_name if len(nickname) == 0 else nickname
    if len(nickname) == 0:
        if ctx.author.nick:
            verbal_test = "nickname"
        else:
            verbal_test = "username"
    else:
        verbal_test = "custom name"

    if len(string_to_test) < 6:
        errors.append(f"Your {verbal_test} is too short. It need to be at least 6 characters.")
    if len(string_to_test) > 32:
        errors.append(f"Your {verbal_test} is too long. It needs to be under 32 characters.")
    if not string_to_test.isalpha():
        errors.append(f"Please only use alphabetical characters in your {verbal_test}.")
    return errors


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
