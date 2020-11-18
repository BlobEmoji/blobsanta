# -*- coding: utf-8 -*-
import asyncio
import random
from datetime import datetime

import discord
from discord.ext import commands

from tools import test_username, check_has_gift, secret_string_wrapper
from . import utils


class Rollback(Exception):
    pass


class CoinDrop(commands.Cog):
    def __init__(self, bot):
        super().__init__()
        self.http = None
        self.session = None
        self.bot = bot
        self.drop_lock = asyncio.Lock()
        self.acquire_lock = asyncio.Lock()
        self.current_gifters = []

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):

        immediate_time = datetime.utcnow()
        if message.author.id in self.current_gifters and not message.guild:
            async with self.bot.db.acquire() as conn:
                last_gift = await conn.fetchval("SELECT last_gift FROM user_data WHERE user_id = $1", message.author.id)

                gift = await conn.fetchrow(
                    """
                    SELECT nickname
                    FROM gifts 
                    INNER JOIN user_data
                    ON target_user_id = user_data.user_id
                    WHERE gifts.user_id = $1 AND active 
                    """, message.author.id)
                if message.content.lower().strip().replace(' ', '') == gift['nickname'].lower().strip().replace(' ', ''):
                    self.current_gifters.remove(message.author.id)
                    self.bot.loop.create_task(self.add_score(message.author, message.created_at))
                    self.bot.logger.info(f"User {message.author.id} guessed gift ({gift['nickname']}) in "
                                     f"{(immediate_time - last_gift).total_seconds()} seconds.")
            return


        if message.content.startswith("."):
            return  # do not drop coins on commands

        if message.channel.id not in self.bot.config.get("drop_channels", []):
            return

        if self.drop_lock.locked():
            return

        # Ignore messages that are more likely to be spammy
        if len(message.content) < 5:
            return
        drop_chance = self.bot.config.get("drop_chance", 0.1)
        if random.random() < drop_chance:
            async with self.bot.db.acquire() as conn:
                record = await conn.fetchrow("SELECT last_gift FROM user_data WHERE user_id = $1", message.author.id)
                if record is not None:
                    if (datetime.utcnow() - record['last_gift']).total_seconds() > self.bot.config.get("cooldown_time", 30):
                        self.bot.logger.info(f"A natural gift has dropped ({message.author.id})")

                        self.bot.loop.create_task(self.create_gift(message.author, message.created_at))

    async def perform_natural_drop(self, user, secret_member, first_attempt):
        async with self.drop_lock:
            secret_string = secret_string_wrapper(secret_member)
            drop_string = f"{'You found a gift!' if first_attempt else 'You found another label on the side of the gift.'} {secret_string}. Fix the label and send the gift by typing the proper label."

            await user.send(drop_string)

    async def create_gift(self, member, when):
        async with self.bot.db.acquire() as conn:

            secret_member_obj = {}
            first_attempt = True

            ret_value = await conn.fetchrow(
                """
                SELECT nickname, user_data.user_id
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
                secret_member_obj = ret_value
            else:
                ret_value = await conn.fetch("SELECT nickname, user_id FROM user_data WHERE user_id != $1", member.id)
                secret_members = [x for x in ret_value]
                self.bot.logger.info(secret_members)
                if not secret_members:
                    self.bot.logger.error(f"I wanted to drop a gift, but I couldn't find any members to send to!")
                    return
                secret_member_obj = random.choice(secret_members)

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
                        INSERT INTO gifts (user_id, target_user_id)
                            VALUES ($1, $2)
                        """,
                        member.id,
                        target_user_id
                    )
        await self.perform_natural_drop(member, secret_member, first_attempt)

    async def _add_score(self, user_id, when):
        await self.bot.db_available.wait()

        async with self.bot.db.acquire() as conn:
            async with conn.transaction():
                gift = await conn.fetchrow(
                    """
                    UPDATE gifts
                    SET active = FALSE
                    WHERE user_id = $1 AND active = TRUE
                    RETURNING target_user_id 
                    """,
                    user_id
                )
                target_user_nickname = await conn.fetchrow(
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
                    RETURNING gifts_sent, nickname
                    """,
                    user_id,
                    when
                )
                return current_user['nickname'], current_user['gifts_sent'], target_user_nickname['nickname']

    async def add_score(self, member, when):
        user_nickname, gifts_sent, target_user_nickname = await self._add_score(member.id, when)
        await member.send(f"You successfully sent the gift to {target_user_nickname}! (Total gifts sent: {gifts_sent})")
        rewards = self.bot.config.get('reward_roles', {})
        await self.bot.get_channel(778410033926897685).send(random.choice(self.bot.config.get("gift_strings")).format(f"**{user_nickname}**", f"**{target_user_nickname}**"))

            # @commands.cooldown(1, 4, commands.BucketType.user)
    # @commands.cooldown(1, 1.5, commands.BucketType.channel)
    # @commands.command("check")
    # async def check_command(self, ctx: commands.Context):
    #     """Check your coin balance"""
    #     if not self.bot.db_available.is_set():
    #         return

    #     currency_name = self.bot.config.get("currency", {})
    #     singular_coin = currency_name.get("singular", "coin")
    #     plural_coin = currency_name.get("plural", "coins")

    #     async with self.bot.db.acquire() as conn:
    #         record = await conn.fetchrow("SELECT coins FROM user_data WHERE user_id = $1", ctx.author.id)

    #         try:
    #             if record is None:
    #                 await ctx.author.send(f"You haven't got any {plural_coin} yet!")
    #             else:
    #                 coins = record["coins"]
    #                 coin_text = f"{coins} {singular_coin if coins==1 else plural_coin}"
    #                 await ctx.author.send(f"You have {coin_text}.")
    #             await ctx.message.delete()
    #         except (discord.Forbidden, discord.HTTPException):
    #             pass

    @commands.command("give_up")
    async def give_up_command(self, ctx: commands.Context):
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
                    gift = await conn.fetchval(
                        """
                        SELECT nickname
                        FROM gifts 
                        INNER JOIN user_data
                        ON target_user_id = user_data.user_id
                        WHERE gifts.user_id = $1 AND active 
                        """, message.author.id)

                    async with conn.transaction():
                        await conn.execute(
                            """
                            DELETE FROM gifts
                            WHERE active = TRUE AND user_id = $1
                            """, ctx.author.id)

                await ctx.send(f"Deleted, the answer was **{gift.lower()}**")
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
        """Check another user's coin balance"""
        if not self.bot.db_available.is_set():
            return
        results = test_username(nickname, ctx)
        if len(results) > 0:
            joined = ',\n'.join(results)
            await ctx.send(f"{ctx.author.mention}, {joined}")
            return
        async with self.bot.db.acquire() as conn:

            record = await conn.fetchval("SELECT * FROM user_data WHERE user_id = $1", ctx.author.id)

            if record is None:
                async with conn.transaction():
                    ret_value = await conn.fetchrow(
                        """
                        INSERT INTO user_data (user_id, nickname)
                        VALUES ($1, $2)
                        ON CONFLICT (nickname) DO UPDATE
                        SET nickname = $3
                        RETURNING *
                        """,

                        ctx.author.id,
                        nickname if nickname != '' else ctx.author.display_name,
                        str(ctx.author.id), ## TO-DO change this to something more visually pleasant
                    )
                await ctx.send(f"{ctx.author.mention} has joined the Blob Santa Event as **{ret_value['nickname']}**!")
            else:
                await ctx.send(f"{ctx.author.mention} You have already joined the event. You can ask a staff member to change your nickname.")

    # @commands.has_permissions(ban_members=True)
    # @commands.check(utils.check_granted_server)
    # @commands.command("peek")
    # async def peek_command(self, ctx: commands.Context, *, target: discord.Member):
    #     """Check another user's coin balance"""
    #     if not self.bot.db_available.is_set():
    #         return

    #     currency_name = self.bot.config.get("currency", {})
    #     singular_coin = currency_name.get("singular", "coin")
    #     plural_coin = currency_name.get("plural", "coins")

    #     async with self.bot.db.acquire() as conn:
    #         record = await conn.fetchrow("SELECT coins FROM user_data WHERE user_id = $1", target.id)

    #         if record is None:
    #             await ctx.send(f"{target.mention} hasn't gotten any {plural_coin} yet!")
    #         else:
    #             coins = record["coins"]
    #             coin_text = f"{coins} {singular_coin if coins==1 else plural_coin}"
    #             await ctx.send(f"{target.mention} has {coin_text}.")

    # @commands.cooldown(1, 4, commands.BucketType.user)
    # @commands.cooldown(1, 1.5, commands.BucketType.channel)
    # @commands.command("stats")
    # async def stats_command(self, ctx: commands.Context, *, mode: str=''):
    #     """Coin leaderboard"""
    #     if not self.bot.db_available.is_set():
    #         return

    #     currency_name = self.bot.config.get("currency", {})
    #     singular_coin = currency_name.get("singular", "coin")
    #     plural_coin = currency_name.get("plural", "coins")

    #     limit = 8

    #     if mode == 'long' and (not ctx.guild or ctx.author.guild_permissions.ban_members):
    #         limit = 25

    #     async with self.bot.db.acquire() as conn:
    #         records = await conn.fetch("""
    #         SELECT * FROM user_data
    #         ORDER BY coins DESC
    #         LIMIT $1
    #         """, limit)

    #         listing = []
    #         for index, record in enumerate(records):
    #             coins = record["coins"]
    #             coin_text = f"{coins} {singular_coin if coins==1 else plural_coin}"
    #             listing.append(f"{index+1}: <@{record['user_id']}> with {coin_text}")

    #     await ctx.send(embed=discord.Embed(description="\n".join(listing), color=0xff0000))

    @commands.cooldown(1, 4, commands.BucketType.user)
    @commands.cooldown(1, 1.5, commands.BucketType.channel)
    @commands.command("list")
    async def list_command(self, ctx: commands.Context):
        """Coin leaderboard"""
        if not self.bot.db_available.is_set():
            return

        async with self.bot.db.acquire() as conn:
            records = await conn.fetch("""
            SELECT nickname, gifts_sent, gifts_received FROM user_data
            ORDER BY 
            gifts_sent DESC,
            gifts_received DESC
            """)

            listing = []
            for index, record in enumerate(records):
                nickname = record["nickname"]
                given = record["gifts_sent"]
                received = record["gifts_received"]
                score_text = f"({given}:{received})"
                listing.append(f"{index+1}: {nickname} {score_text}")
        embed = discord.Embed(color=0x69e0a5)
        embed.set_footer(text='A list of all the people participating in gift-giving.')
        embed.set_author(name="Blob Santa\'s List",icon_url = 'https://cdn.discordapp.com/attachments/542422265254641674/778688484084678656/googlegiftmint.png')
        while len(listing) > 0:
            embed.add_field(name='\u200b', value="\n".join(listing[:24]))
            del listing[:24]
        await ctx.send(embed=embed)

    @commands.check(utils.check_granted_server)
    @commands.command("reset")
    async def reset(self, ctx: commands.Context):
        """Reset users' coin accounts"""
        if not self.bot.db_available.is_set():
            await ctx.send("No connection to database.")
            return

        async with self.bot.db.acquire() as conn:
            record = await conn.fetchrow("SELECT * FROM user_data WHERE user_id = $1", ctx.author.id)
            if record is None:
                await ctx.send("This user doesn't have a database entry.")
                return

            async with conn.transaction():
                await conn.execute("DELETE FROM user_data WHERE user_id = $1", ctx.author.id)

            await ctx.send(f"Cleared entry for {ctx.author.id}")
    # Testing purposes only
    # DELETE LATER
    @commands.check(utils.check_granted_server)
    @commands.command("add_dummy")
    async def add_dummy(self, ctx: commands.Context, nickname: str=''):
        results = test_username(nickname, ctx)
        if len(results) > 0:
            joined = ',\n'.join(results)
            await ctx.send(f"{ctx.author.mention}, {joined}")
            return
        async with self.bot.db.acquire() as conn:
            async with conn.transaction():
                ret_value = await conn.fetchval(
                    """
                    INSERT INTO user_data (user_id, nickname)
                    VALUES ($1, $2)
                    ON CONFLICT (nickname) DO UPDATE
                    SET nickname = $3
                    RETURNING nickname
                    """,
                    random.randint(0, 10000),
                    nickname if nickname != '' else f"Dummy{random.randint(0, 100000)}",
                    f"Dummy{random.randint(0, 100000)}",  ## TO-DO change this to something more visually pleasant
                )
                await ctx.send(f"Dummy has joined the Blob Santa Event as **{ret_value}**!")
    # Testing purposes only
    # DELETE LATER
    @commands.check(utils.check_granted_server)
    @commands.command("delete_dummies")
    async def reset(self, ctx: commands.Context):
        """Reset users' coin accounts"""
        if not self.bot.db_available.is_set():
            await ctx.send("No connection to database.")
            return

        async with self.bot.db.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM user_data WHERE user_id <= 10000")
            await ctx.send(f"Cleared entry for dummies")
    
    @commands.has_permissions(ban_members=True)
    @commands.check(utils.check_granted_server)
    @commands.command("reset_user")
    async def reset_user(self, ctx: commands.Context, user: discord.User):
        """Reset users' coin accounts"""
        if not self.bot.db_available.is_set():
            await ctx.send("No connection to database.")
            return

        async with self.bot.db.acquire() as conn:
            record = await conn.fetchrow("SELECT * FROM user_data WHERE user_id = $1", user.id)
            if record is None:
                await ctx.send("This user doesn't have a database entry.")
                return

            confirm_text = f"confirm {random.randint(0, 999999):06}"

            await ctx.send(f"Are you sure? This user has {record['gifts_sent']} coins, last picking one up at "
                           f"{record['last_gift']} UTC. (type '{confirm_text}' or 'cancel')")

            def wait_check(msg):
                return msg.author.id == ctx.author.id and msg.content.lower() in (confirm_text, "cancel")

            try:
                validate_message = await self.bot.wait_for('message', check=wait_check, timeout=30)
            except asyncio.TimeoutError:
                await ctx.send(f"Timed out request to reset {user.id}.")
                return
            else:
                if validate_message.content.lower() == 'cancel':
                    await ctx.send("Cancelled.")
                    return

                async with conn.transaction():
                    await conn.execute("DELETE FROM user_data WHERE user_id = $1", user.id)

                await ctx.send(f"Cleared entry for {user.id}")

    # @commands.has_permissions(ban_members=True)
    # @commands.check(utils.check_granted_server)
    # @commands.command("force_spawn")
    # async def force_spawn_command(self, ctx: commands.Context, where: discord.TextChannel = None):
    #     """Force spawns a coin in a given channel."""
    #     if where is None:
    #         await ctx.send("You must specify a drop channel.")
    #         return

    #     if not self.bot.db_available.is_set():
    #         await ctx.send("Cannot access the db right now.")
    #         return

    #     if self.drop_lock.locked():
    #         await ctx.send("A coin is already spawned somewhere.")
    #         return

    #     if where.id not in self.bot.config.get("drop_channels", []):
    #         await ctx.send("Channel is not in drop list.")
    #         return

    #     coin_id = '%016x' % random.randrange(16 ** 16)
    #     self.bot.logger.info(f"A random coin was force dropped by {ctx.author.id} ({coin_id})")
    #     self.last_coin_id = coin_id
    #     self.bot.loop.create_task(self.attempt_add_reaction(ctx.message, "\N{WHITE HEAVY CHECK MARK}"))
    #     await self.perform_natural_drop(where, coin_id)


def setup(bot):
    bot.add_cog(CoinDrop(bot))
