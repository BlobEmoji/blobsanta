import re

from discord.ext import commands


def test_username(nickname: str, ctx: commands.Context) -> list:
    errors = []
    if len(nickname) < 6:
        errors.append("Your username is too short. It need to be at least 6 characters.")
    elif len(nickname) > 32:
        errors.append("Your username is too long. It needs to be under 32 characters.")
    elif not nickname.isalpha():
        errors.append("Please only use alphabetical characters in your nickname.")
    elif not re.match('^[a-zA-Z0-9_]+$', ctx.author.display_name) and nickname == '':
        errors.append("Your username is invalid. Please choose a nickname with `.join <nickname>`.")
    return errors

