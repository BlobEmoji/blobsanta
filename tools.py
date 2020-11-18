import re

from discord.ext import commands


def test_username(nickname: str, ctx: commands.Context) -> list:
    errors = []
    string_to_test = ctx.author.username if len(nickname) == 0 else nickname
    verbal_test = "username" if len(nickname) == 0 else "nickname"

    if len(string_to_test) < 6:
        errors.append(f"Your {verbal_test} is too short. It need to be at least 6 characters.")
    if len(string_to_test) > 32:
        errors.append(f"Your {verbal_test} is too long. It needs to be under 32 characters.")
    if not string_to_test.isalpha():
        errors.append(f"Please only use alphabetical characters in your {verbal_test}.")
    return errors
