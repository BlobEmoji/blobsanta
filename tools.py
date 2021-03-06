import random
import re

from typing import List
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
        errors.append(f"Your {verbal_test} is too short, it needs to be at least 4 characters")
    if len(string_to_test) > 16:
        errors.append(f"Your {verbal_test} is too long, it needs to be under 16 characters")
    if string_to_test.lower().startswith("confirm"):
        errors.append(f"Your {verbal_test} is contains disallowed prefix 'confirm'")
    if not (string_to_test.isalpha() and string_to_test.isascii()):
        errors.append(f"Please only use alphabetical characters in your {verbal_test}")
    if len(set(string_to_test)) == 1:
        errors.append(f"Please use more than one unique character in your {verbal_test}")
    return errors


def secret_substring(name: str) -> str:
    length = min(random.randint(3, 4),len(name)-1)
    start = random.randint(0, len(name) - length)
    result = name[start:start + length]
    return f"Label contains: `{result}`"


def secret_smudge(name: str) -> str:
    smudged = random.sample(range(len(name)), round(len(name) * .5))
    result = list(name)
    for i in smudged:
        result[i] = '#'
    result = ''.join(result)
    return f"Find the missing letters: `{result}`"


def secret_scramble(name: str, attempts=10) -> str:
    scrambled = list(name)
    random.shuffle(scrambled)
    result = ''.join(scrambled)
    if result == name and attempts != 0:
        return secret_scramble(name, attempts-1)
    return f"Unscramble: `{result}`"

def secret_string_wrapper(secret_member: str, bad_phrases: List[str] ) -> str:
    secret_array = [secret_scramble, secret_substring, secret_smudge]
    secret_string = random.choice(secret_array)(secret_member)

    # Check for bad words
    secret_string_norm = secret_string.lower() # lowercase
    secret_string_norm = re.sub('#', '', secret_string_norm) # remove smudging
    if any(phrase in secret_string_norm for phrase in bad_phrases): # bad words
        secret_string = secret_string_wrapper(secret_member, bad_phrases) # try again

    return secret_string
