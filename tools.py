import random

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

    if len(string_to_test) < 4:
        errors.append(f"Your {verbal_test} is too short. It need to be at least 4 characters.")
    if len(string_to_test) > 25:
        errors.append(f"Your {verbal_test} is too long. It needs to be under 25 characters.")
    if string_to_test.lower().startswith("confirm"):
        errors.append(f"Your {verbal_test} is blacklisted.")
    if not (string_to_test.isalpha() and string_to_test.isascii()):
        errors.append(f"Please only use alphabetical characters in your {verbal_test}.")
    return errors


def secret_substring(name: str) -> str:
    length = min(random.randint(3, 4),len(name)-1)
    start = random.randint(0, len(name) - length)
    result = name[start:start + length]
    return f"Label contains: `{result}`"


def secret_smudge(name: str) -> str:
    smudged = random.sample(range(len(name)), round(len(name) * .7))
    result = list(name)
    for i in smudged:
        result[i] = '#'
    result = ''.join(result)
    return f"Find the missing letters: `{result}`"


def secret_scramble(name: str) -> str:
    scrambled = list(name)
    random.shuffle(scrambled)
    result = ''.join(scrambled)
    return f"Unscramble: `{result}`"


def secret_string_wrapper(secret_member: str) -> str:
    secret_array = [secret_scramble, secret_substring, secret_smudge]
    secret_string = random.choice(secret_array)(secret_member)
    return secret_string
