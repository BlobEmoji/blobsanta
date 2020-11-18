import re

from discord.ext import commands


def test_username(nickname: str, ctx: commands.Context):
    if len(nickname) < 6:
        await ctx.send(f"{ctx.author.mention} Your username is too short. It need to be at least 6 characters.")
        return True
    elif len(nickname) > 32:
        await ctx.send(f"{ctx.author.mention} Your username is too long. It needs to be under 32 characters.")
        return True
    elif not nickname.isalpha():
        await ctx.send(f"{ctx.author.mention} Please only use alphanumeric characters in your nickname.")
        return True
    elif not re.match('^[a-zA-Z0-9_]+$', ctx.author.display_name) and nickname == '':
        await ctx.send(
            f"{ctx.author.mention} Your username is invalid. Please choose a nickname with `.join <nickname>`.")
        return True
    return False
