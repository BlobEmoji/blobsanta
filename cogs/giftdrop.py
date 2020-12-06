# -*- coding: utf-8 -*-
import asyncio
import collections
import io
import math
import random
import re
from datetime import datetime, timedelta

import discord
import toml
import numpy as np
from asyncpg.exceptions import UniqueViolationError
from discord.ext import commands

from db_utils import fetch_gift_nickname, last_gift_from_db, check_has_gift, check_is_in
from tools import test_username, secret_string_wrapper
from . import utils


class Rollback(Exception):
    pass


class GiftDrop(commands.Cog):
    def __init__(self, bot):
        super().__init__()
        self.http = None
        self.session = None
        self.bot = bot
        self.gift_lock = asyncio.Lock()
        self.current_gifters = []
        self.present_stash = []
        self.label_stash = {}
        self.log_stash = []
        self.users_last_message = {}
        self.users_last_channel = {}
        self.users_drop_stash = {}
        self.last_label = None
        self.last_user = None
        self.giftstrings = []

        with open('giftstrings.toml', 'r', encoding='utf-8') as fp:
            self.giftstrings = toml.load(fp)['giftstrings']

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Do not drop gifts on commands
        if message.content.startswith(".") or message.content.lower().startswith("confirm"): return

        immediate_time = datetime.utcnow()
        if message.author.id in self.current_gifters and not message.guild:
            async with self.bot.db.acquire() as conn:
                last_gift = await last_gift_from_db(conn, message.author.id)

                gift = await fetch_gift_nickname(conn, message.author.id)
                if message.content.lower().strip().replace(' ', '') == gift.lower().strip().replace(' ', ''):
                    calculated_time = (immediate_time - last_gift).total_seconds()
                    self.current_gifters.remove(message.author.id)
                    self.bot.loop.create_task(self.add_score(message.author, message.created_at))
                    self.bot.logger.info(
                        f"User {message.author.id} guessed gift ({gift}) in {calculated_time} seconds."
                    )
                else:
                    await message.add_reaction(self.bot.config.get('wrong_emoji'))
            return

        if message.channel.id not in self.bot.config.get("drop_channels", []): return
        self.users_last_channel[message.author.id] = {'name': message.channel.name, 'id': message.channel.id}

        # Remove markdown
        for pattern in ["*", "__", "~~", "||", "`", ">"]:
            message.content = message.content.replace(pattern, "")
        # Ignore messages that are more likely to be spammy, chain messages and emoji-only messages.
        if len(re.sub(r"<a?:\w{2,32}:\d{15,21}>", "", message.content)) < 5 or self.last_user == message.author.id:
            return

        self.last_user = message.author.id

        if not message.author.id in self.users_last_message or (datetime.now()-self.users_last_message[message.author.id]).total_seconds() > self.bot.config.get("recovery_time", 10):
            self.users_last_message[message.author.id] = datetime.now()
            async with self.bot.db.acquire() as conn:
                last_gift = await last_gift_from_db(conn, message.author.id)
                if last_gift is not None:
                    if (datetime.utcnow() - last_gift).total_seconds() > self.bot.config.get("cooldown_time", 30):
                        drop_chance = self.bot.config.get("drop_chance", 0.1)

                        if not message.author.id in self.users_drop_stash or len(self.users_drop_stash[message.author.id]) == 0:
                            self.users_drop_stash[message.author.id] = [True]*int(20*drop_chance) + [False]*int(20*(1-drop_chance))

                        drop = self.users_drop_stash[message.author.id].pop(random.randrange(len(self.users_drop_stash[message.author.id])))

                        if drop:
                            self.users_drop_stash[message.author.id] = [True]*int(20*drop_chance) + [False]*int(20*(1-drop_chance))
                            self.bot.logger.info(f"A natural gift has dropped ({message.author.id})")
                            self.bot.loop.create_task(self.create_gift(message.author, message.created_at))

    async def perform_natural_drop(self, user, secret_member, first_attempt, gift_icon_index):
        secret_string = secret_string_wrapper(secret_member)

        if first_attempt: description = 'Type the name of the finished label to send the gift!'
        else: description = 'You have another chance. Type the name of \nthe finished label to send the gift!'

        embed = discord.Embed(
            title='New Gift!' if first_attempt else 'Another Hint!',
            description=description,
            color=0xff0000 if first_attempt else 0xff8500
        )
        embed.set_thumbnail(url=self.bot.config.get('gift_icons')[gift_icon_index])
        embed.add_field(name='Hint', value=secret_string)
        if not first_attempt:
            embed.set_footer(text=random.choice(self.bot.config.get('hints')))
        await user.send(embed=embed)

    async def create_gift(self, member, when):
        async with self.bot.db.acquire() as conn:
            first_attempt = True
            ret_value = await conn.fetchrow(
                """
                SELECT nickname, user_data.user_id, gift_icon
                FROM gifts
                INNER JOIN user_data
                ON target_user_id = user_data.user_id
                WHERE gifts.user_id = $1 AND active 
                """,
                member.id
            )
            if member.id not in self.current_gifters:
                self.current_gifters.append(member.id)
            if ret_value is not None:
                first_attempt = False
                gift_icon_index = ret_value['gift_icon']
                secret_member_obj = ret_value
            else:
                secret_members = await conn.fetch("SELECT nickname, user_id FROM user_data ORDER BY creation_date ASC")

                last_stashed = None
                if len(self.present_stash) == 1:
                    last_stashed = self.present_stash.pop()
                if len(self.present_stash) == 0 or random.randint(0,100) < 5:
                    self.present_stash = [*range(len(self.bot.config.get('gift_icons')))]
                    if last_stashed:
                        self.present_stash.pop(last_stashed)

                gift_icon_index = last_stashed or self.present_stash.pop(random.randrange(len(self.present_stash)))
                if not secret_members:
                    self.bot.logger.error(f"I wanted to drop a gift, but I couldn't find any members to send to!")
                    return

                # When the list has no available label (excluding current user)
                if not member.id in self.label_stash:
                    # Create label list with the current user removed
                    self.label_stash[member.id] = [i for i, s in enumerate (secret_members) if s['user_id'] != member.id]

                # Get the selected member object
                secret_member_obj = secret_members[self.label_stash[member.id].pop(random.randrange(len(self.label_stash[member.id])))]

                # Repopulate gift list on empty
                if len(self.label_stash[member.id]) == 0 or random.random() < 0.05:
                    self.label_stash[member.id] = [i for i, s in enumerate (secret_members) if not (s['user_id'] == secret_member_obj['user_id'] or s['user_id'] == member.id) ]
            secret_member = secret_member_obj['nickname']
            target_user_id = secret_member_obj['user_id']

            async with conn.transaction():
                await conn.fetch(
                    """
                    UPDATE user_data 
                    SET last_gift = $2
                    WHERE user_id = $1
                    """,
                    member.id,
                    when
                )
                if first_attempt:
                    await conn.fetch(
                        """
                        INSERT INTO gifts (user_id, target_user_id, gift_icon)
                            VALUES ($1, $2, $3)
                        """,
                        member.id,
                        target_user_id,
                        gift_icon_index
                    )
        await self.perform_natural_drop(member, secret_member, first_attempt, gift_icon_index)

    async def _add_score(self, user_id, when):
        await self.bot.db_available.wait()

        async with self.bot.db.acquire() as conn:
            async with conn.transaction():
                gift = await conn.fetchrow(
                    """
                    UPDATE gifts
                    SET active = FALSE, is_sent = TRUE
                    WHERE user_id = $1 AND active = TRUE
                    RETURNING target_user_id, gift_icon
                    """,
                    user_id
                )
                target_user = await conn.fetchrow(
                    """
                    UPDATE user_data
                    SET gifts_received = gifts_received + 1
                    WHERE user_id = $1
                    RETURNING nickname
                    """,
                    gift['target_user_id']
                )
                current_user = await conn.fetchrow(
                    """
                    UPDATE user_data 
                    SET last_gift = $2, gifts_sent = gifts_sent + 1
                    WHERE user_id = $1 
                    RETURNING gifts_sent, gifts_received, nickname
                    """,
                    user_id,
                    when
                )

                ret_gift = {
                    'gift_icon': self.bot.config.get('gift_icons')[gift['gift_icon']],
                    'gift_emoji': self.bot.config.get('gift_emojis')[gift['gift_icon']]
                }
                ret_user = {
                    'nickname': current_user['nickname'],
                    'gifts_sent': current_user['gifts_sent'],
                    'gifts_received': current_user['gifts_received']
                }
                ret_target = {
                    'user_id': gift['target_user_id'],
                    'nickname': target_user['nickname'],
                    'avatar_url': (await self.bot.fetch_user(gift['target_user_id'])).avatar_url_as(format=None, static_format='webp', size=256)
                }
                return ret_gift, ret_user, ret_target

    async def add_score(self, member, when):
        gift, user, target = await self._add_score(member.id, when)
        log_channel = self.bot.get_channel(self.bot.config.get("present_log"))
        guild = log_channel.guild

        if member.id in self.users_last_channel:
            return_name = f"#{self.users_last_channel[member.id]['name']}"
            return_id = self.users_last_channel[member.id]['id']
        else:
            return_name = 'chat'
            return_id = self.bot.config.get('drop_channels')[0]

        return_link = f'[← Back to {return_name}](https://discord.com/channels/{guild.id}/{return_id}/)'
        description = f"**TO:** {target['nickname']}\n**FROM:** {user['nickname']}\n{return_link}"
        embed = discord.Embed(description=description, color=0x69e0a5)

        embed.set_thumbnail(url=target['avatar_url'])
        embed.set_author(name="Gift Sent!", icon_url=gift['gift_icon'])
        embed.set_footer(text=f"Total Gifts Sent: {user['gifts_sent']}")
        await member.send(embed=embed)

        rewards = self.bot.config.get('reward_roles', {})

        if len(self.log_stash) <= 1 or random.randint(0, 100) < 3:
            self.log_stash = [*range(len(self.giftstrings))]

        log_message = f'{gift["gift_emoji"]} {self.giftstrings[self.log_stash.pop(random.randrange(len(self.log_stash)))]}'
        await log_channel.send(log_message.format(f"**{user['nickname']}**", f"**{target['nickname']}**", gift["gift_emoji"]))

        # Check if the user reached the gifts sent/received thresholds
        guild_member = guild.get_member(member.id) or await guild.fetch_member(member.id)
        give_role = False
        role_to_check = None

        for role_params in rewards["roles_list"]:
            if user['gifts_sent'] >= role_params["nbSent"] and user['gifts_received'] >= role_params["nbReceived"]:
                give_role = True
                role_to_check = role_params["roleId"]

        # Stop if no new threshold is met
        if not give_role:
            return

        # Stop if the user already has the given role (to prevent adding the same role multiple times on a member)
        for role in guild_member.roles:
            if role.id == role_to_check:
                return

        # Add the role to the user
        role = guild.get_role(role_to_check)

        if role is None:
            self.bot.logger.warning(f"Failed to find reward role for {user['gifts_sent']} gifts sent.")
            return

        try:
            await guild_member.add_roles(role, reason=f"Reached {user['gifts_sent']} gifts sent reward.")
        except discord.HTTPException:
            self.bot.logger.exception(f"Failed to add reward role for {user['gifts_sent']} gifts sent to {member!r}.")

    @commands.cooldown(1, 4, commands.BucketType.user)
    @commands.cooldown(1, 1.5, commands.BucketType.channel)
    @commands.command("check")
    async def check_command(self, ctx: commands.Context):
        """Check your gifts sent and received"""
        if not self.bot.db_available.is_set():
            return

        async with self.bot.db.acquire() as conn:
            record = await conn.fetchrow("SELECT gifts_sent, gifts_received, nickname FROM user_data WHERE user_id = $1", ctx.author.id)

            try:
                if record is None:
                    await ctx.author.send(f"You haven't sent any gifts yet! Use `.join` in a channel to join the fun!")
                else:
                    await ctx.author.send(f"You ({record['nickname']}) have sent {record['gifts_sent']} and received {record['gifts_received']} 🎁 **Gifts**.")
                await ctx.message.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass

    @commands.command("giveup")
    async def giveup_command(self, ctx: commands.Context):
        """Give up on a label"""
        message: discord.Message = ctx.message
        if isinstance(message.channel, discord.DMChannel):
            check = await check_has_gift(self.bot.db, ctx.author.id)

            if not check:
                await ctx.send("You don't have anything to give up on")
                return

            confirm_text = f"confirm {random.randint(0, 999999):06}"
            await ctx.send(f"Are you sure you want to give up?. Type '{confirm_text}' or 'cancel'")

            def wait_check(msg):
                return msg.author.id == ctx.author.id and msg.content.lower() in (confirm_text, "cancel")

            try:
                validate_message = await self.bot.wait_for('message', check=wait_check, timeout=30)
            except asyncio.TimeoutError:
                await ctx.send(f"Timed out request to reset {ctx.author.id}.")
                return
            else:
                if validate_message.content.lower() == 'cancel':
                    await ctx.send("Cancelled.")
                    return

                async with self.bot.db.acquire() as conn:
                    nickname = await fetch_gift_nickname(conn, message.author.id)

                    async with conn.transaction():
                        await conn.execute(
                            """
                            UPDATE gifts
                            SET active = FALSE
                            WHERE user_id = $1 AND active = TRUE
                            """, ctx.author.id)

                await ctx.send(f"Deleted, the answer was **{nickname.lower()}**")
        else:
            async with self.bot.db.acquire() as conn:
                check = await check_has_gift(self.bot.db, ctx.author.id)
                if check:
                    await ctx.send("You can only give up on gifts in DMs")
                else:
                    await ctx.send("You don't have anything to give up on")

    @commands.check(utils.check_granted_server)
    @commands.command("join")
    async def join_command(self, ctx: commands.Context, *, nickname: str=''):
        """Join the event"""
        if not self.bot.db_available.is_set():
            return
        results = test_username(nickname, ctx)
        if len(results) > 0:
            joined = ';\n'.join(results)
            await ctx.send(f"{ctx.author.mention}, {joined}.\nYou may use a custom name by using `.join <nickname>`")
            return
        async with self.bot.db.acquire() as conn:

            check = await check_is_in(conn, ctx.author.id)

            if check is False:
                async with conn.transaction():
                    ret_value = await conn.fetchrow(
                        """
                        INSERT INTO user_data (user_id, nickname)
                        VALUES ($1, $2)
                        ON CONFLICT (nickname) DO NOTHING
                        RETURNING *
                        """,
                        ctx.author.id,
                        nickname if nickname != '' else ctx.author.display_name
                    )
                    if ret_value is None:
                        await ctx.send(f"{ctx.author.mention} Sorry, that name is already taken. Please try a different nickname with `.join <nickname>`.")
                    else:
                        await ctx.send(f"{ctx.author.mention} has joined the Blob Santa Event as **{ret_value['nickname']}**!")
            else:
                await ctx.send(f"{ctx.author.mention} You have already joined the event. You can ask a staff member to change your nickname.")

    @commands.has_permissions(ban_members=True)
    @commands.check(utils.check_granted_server)
    @commands.command("peek")
    async def peek_command(self, ctx: commands.Context, *, target: discord.Member):
        """Check another user's gifts"""
        if not self.bot.db_available.is_set():
            return

        async with self.bot.db.acquire() as conn:
            record = await conn.fetchrow("""
            SELECT gifts_sent, gifts_received, nickname 
            FROM user_data 
            WHERE user_id = $1""", target.id)

            if record is None:
                await ctx.send(f"{target.mention} hasn't gotten any gifts yet!")
            else:
                await ctx.send(f"{target.mention} {record['nickname']} has sent {record['gifts_sent']} and received {record['gifts_received']} gifts.")

    @commands.has_permissions(ban_members=True)
    @commands.check(utils.check_granted_server)
    @commands.command("change_nickname")
    async def change_nickname_command(self, ctx: commands.Context, target: discord.Member, nickname: str = ''):
        """Change another user's nickname"""
        if not self.bot.db_available.is_set():
            return

        async with self.bot.db.acquire() as conn:
            if not await check_is_in(conn, target.id):
                await ctx.send(
                    f"{ctx.author.mention} Hey, {target.mention} doesn't seem to be participating currently."
                )

        if nickname == '':
            await ctx.send(f"{ctx.author.mention} Please supply a nickname for the user with `.change_nickname <user> <nickname>`")
            return

        results = test_username(nickname, ctx)
        if len(results) > 0:
            joined = ',\n'.join(results)
            await ctx.send(f"{ctx.author.mention}, {joined}")
            return

        async with self.bot.db.acquire() as conn:
            async with conn.transaction():
                try:
                    ret_value = await conn.fetchrow(
                        """
                        UPDATE user_data 
                        SET nickname = $2
                        WHERE user_id = $1
                        RETURNING *
                        """,
                        target.id,
                        nickname
                    )
                    if ret_value is None:
                        await ctx.send(f"{ctx.author.mention} Sorry, that user has not joined the event yet.")
                    else:
                        await ctx.send(f"{ctx.author.mention}, The nickname was successfully changed to **{ret_value['nickname']}**!")
                except UniqueViolationError:
                    await ctx.send(f"{ctx.author.mention} Sorry, that name is already taken.")
                    pass

    @commands.cooldown(1, 4, commands.BucketType.user)
    @commands.cooldown(1, 1.5, commands.BucketType.channel)
    @commands.command("stats")
    async def stats_command(self, ctx: commands.Context, *, mode: str = ''):
        """Gift leaderboard"""
        if not self.bot.db_available.is_set():
            return

        limit = 8

        if mode == 'long' and (not ctx.guild or ctx.author.guild_permissions.ban_members):
            limit = 25

        async with self.bot.db.acquire() as conn:
            records = await conn.fetch("""
            SELECT * FROM user_data
            ORDER BY gifts_sent DESC
            LIMIT $1
            """, limit)

            listing = []
            for index, record in enumerate(records):
                gifts = record["gifts_sent"]
                gift_text = f"{gifts} gift{'' if gifts==1 else 's'} sent"
                listing.append(f"{index+1}: <@{record['user_id']}> with {gift_text} as {record['nickname']}")

        await ctx.send(embed=discord.Embed(description="\n".join(listing), color=0xff0000))

    @commands.cooldown(1, 4, commands.BucketType.user)
    @commands.cooldown(1, 1.5, commands.BucketType.channel)
    @commands.command("list")
    async def list_command(self, ctx: commands.Context):
        """List of all participating gifters"""
        if not self.bot.db_available.is_set():
            return

        async with self.bot.db.acquire() as conn:
            records = await conn.fetch("""
            SELECT nickname, gifts_sent, gifts_received FROM user_data
            ORDER BY lower(nickname)
            """)

            listing = []
            for index, record in enumerate(records):
                nickname = record["nickname"]
                given = record["gifts_sent"]
                received = record["gifts_received"]
                score_text = f"({given}:{received})"
                listing.append(f"{nickname} {score_text}")
        embed = discord.Embed(color=0x69e0a5)
        embed.set_footer(text='A list of all the people participating in gift-giving.')
        embed.set_author(name="Blob Santa\'s List", icon_url = self.bot.config.get("embed_url"))
        while len(listing) > 0:
            embed.add_field(name='\u200b', value="\n".join(listing[:24]))
            del listing[:24]
        try:
            await ctx.author.send(embed=embed)
            await ctx.message.delete()
        except (discord.Forbidden, discord.HTTPException):
            pass

    @commands.has_permissions(ban_members=True)
    @commands.check(utils.check_granted_server)
    @commands.command("extract_data")
    async def extract_data_command(self, ctx: commands.Context, mode: str='', n_bins: int=600, all: bool=False):
        """Timeseries csv file for data visualization"""
        if not self.bot.db_available.is_set():
            await ctx.send("No connection to database.")
            return
        await ctx.send("Extracting data...")
        start_time = datetime.utcnow()
        async with self.bot.db.acquire() as conn:
            record = await conn.fetchrow("SELECT MIN(activated_date) as min_date, MAX(activated_date) as max_date FROM gifts")
            seconds = math.ceil((record['max_date']-record['min_date']).total_seconds()/(n_bins-1))
            bins = [(record['min_date'] + timedelta(seconds=seconds*i)) for i in range(n_bins)]
            features = ['name', 'pic'] + [x.strftime('%m/%d %H:%M') for x in bins]
            data = [features]
            if mode in ['', 'sent']:
                users = await conn.fetch("SELECT user_id,nickname FROM user_data WHERE gifts_sent >= $1 ORDER BY gifts_sent DESC", 0 if all else 1)
                for user in users:
                    dates = np.array([np.datetime64(date['activated_date']) for date in await conn.fetch("SELECT activated_date FROM gifts WHERE user_id = $1 AND is_sent = TRUE", user['user_id'])]).view('i8')

                    inds = list(np.digitize(dates, np.array(bins, dtype='datetime64').view('i8')))
                    row = [user['nickname'], str((await self.bot.fetch_user(user['user_id'])).avatar_url_as(format='png', static_format='png', size=128))] + [0] * len(bins)
                    count = 0
                    for i in range(len(row)-2):
                        for ind in inds:
                            if ind == i:
                                count += 1
                        row[i+2] = count if count != 0 else ""

                    data.append(row)
            elif mode == 'received':
                users = await conn.fetch("SELECT user_id,nickname FROM user_data")
                for user in users:
                    dates = np.array([np.datetime64(date['activated_date']) for date in await conn.fetch("SELECT activated_date FROM gifts WHERE target_user_id = $1 AND is_sent = TRUE", user['user_id'])]).view('i8')

                    inds = list(np.digitize(dates, np.array(bins, dtype='datetime64').view('i8')))
                    row = [user['nickname'], str((await self.bot.fetch_user(user['user_id'])).avatar_url_as(format='png', static_format='png', size=128))] + [0] * len(bins)
                    count = 0
                    for i in range(len(row)-2):
                        for ind in inds:
                            if ind == i:
                                count += 1
                        row[i+2] = count if count != 0 else ""

                    data.append(row)
            elif mode == 'presents':
                presents = [*range(len(self.bot.config.get('gift_icons')))]
                for present in presents:
                    dates = np.array([np.datetime64(date['activated_date']) for date in await conn.fetch("SELECT activated_date FROM gifts WHERE gift_icon = $1 AND is_sent = TRUE", present)]).view('i8')

                    inds = list(np.digitize(dates, np.array(bins, dtype='datetime64').view('i8')))
                    row = [present, self.bot.config.get('gift_icons')[present]] + [0] * len(bins)
                    count = 0
                    for i in range(len(row)-2):
                        for ind in inds:
                            if ind == i:
                                count += 1
                        row[i+2] = count if count != 0 else ""

                    data.append(row)
            text = "\n".join(','.join([str(s) for s in x]) for x in data)

            await ctx.send(f"Finished! Took {(datetime.utcnow()-start_time).total_seconds()} seconds.", file=discord.File(filename="stats.csv", fp=io.BytesIO(text.encode("utf8"))))

    @commands.has_permissions(ban_members=True)
    @commands.check(utils.check_granted_server)
    @commands.command("reset_user")
    async def reset_user_command(self, ctx: commands.Context, *, target: discord.Member):
        """Reset users' accounts"""
        if not self.bot.db_available.is_set():
            await ctx.send("No connection to database.")
            return
        async with self.bot.db.acquire() as conn:
            record = await conn.fetchrow("SELECT * FROM user_data WHERE user_id = $1", target.id)
            if record is None:
                await ctx.send("This user doesn't have a database entry.")
                return

            confirm_text = f"confirm {random.randint(0, 999999):06}"

            await ctx.send(f"Are you sure? This user has {record['gifts_sent']} gifts sent, last picking one up at "
                           f"{record['last_gift']} UTC. (type '{confirm_text}' or 'cancel')")

            def wait_check(msg):
                return msg.author.id == ctx.author.id and msg.content.lower() in (confirm_text, "cancel")

            try:
                validate_message = await self.bot.wait_for('message', check=wait_check, timeout=30)
            except asyncio.TimeoutError:
                await ctx.send(f"Timed out request to reset {target.id}.")
                return
            else:
                if validate_message.content.lower() == 'cancel':
                    await ctx.send("Cancelled.")
                    return

                async with conn.transaction():
                    await conn.execute("DELETE FROM user_data WHERE user_id = $1", target.id)

                await ctx.send(f"Cleared entry for {target.id}")

    @commands.has_permissions(ban_members=True)
    @commands.check(utils.check_granted_server)
    @commands.command("reload_strings")
    async def reload_strings_command(self, ctx: commands.Context):
        """Reload gift strings from file"""
        old_strings = collections.Counter(self.giftstrings)

        with open('giftstrings.toml', 'r', encoding='utf-8') as fp:
            self.giftstrings = toml.load(fp)['giftstrings']

        self.log_stash = [*range(len(self.giftstrings))]

        new_strings = collections.Counter(self.giftstrings)

        strings_removed = list(old_strings - new_strings)
        strings_added = list(new_strings - old_strings)

        if len(strings_removed) == 0 and len(strings_added) == 0:
            response = 'No strings added or removed.'

        else:
            texts = []
            strings = []

            if strings_added:
                texts.append(f'{len(strings_added)} string(s) added.')

                for string in strings_added:
                    strings.append(f'+ "{string}"')

            if strings_removed:
                texts.append(f'{len(strings_removed)} string(s) removed.')

                for string in strings_removed:
                    strings.append(f'- "{string}"')

            text = ' '.join(texts)
            diff = '\n'.join(strings)

            if len(diff) > 1700: diff = '# Diff is too long sorry :('

            response = f"{text}\n```diff\n{diff}\n```"

        await ctx.send(f'Strings reloaded: {response}')

def setup(bot):
    bot.add_cog(GiftDrop(bot))
