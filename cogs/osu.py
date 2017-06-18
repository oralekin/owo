import os
import discord
from discord.ext import commands
from discord.utils import find
from __main__ import send_cmd_help
import random, time, datetime, json
import aiohttp
import asyncio
import pyoppai
from pippy.beatmap import Beatmap
import wget
import re, operator
import urllib.request
import numpy
from pymongo import MongoClient
try:
    from bs4 import BeautifulSoup
except:
    raise RuntimeError("bs4 required: pip install beautifulsoup4")
from .utils.dataIO import fileIO
from cogs.utils import checks
from subprocess import Popen, CalledProcessError, PIPE, STDOUT
import logging

prefix = fileIO("data/red/settings.json", "load")['PREFIXES'][0]
help_msg = [
            "**No linked account (`{}osuset user [username]`) or not using **`{}command [username] [gamemode]`".format(prefix, prefix),
            "**No linked account (`{}osuset user [username]`)**".format(prefix)
            ]
modes = ["osu", "taiko", "ctb", "mania"]
client = MongoClient()
db = client['owo_database_2']
log = logging.getLogger("red.osu")
log.setLevel(logging.DEBUG)

def print_database():
    users = []
    for user in db.user_settings.find({}):
        data = db.user_settings.find_one({'_id':user})
        users.append(data)
    fileIO("data/osu/user_print.json", "save", users)

class Osu:
    """Cog to give osu! stats for all gamemodes."""

    def __init__(self, bot):
        self.bot = bot
        self.osu_api_key = fileIO("data/osu/apikey.json", "load")
        self.osu_settings = fileIO("data/osu/osu_settings.json", "load")
        self.num_max_prof = 8
        self.max_map_disp = 3
        self.max_requests = 1050 # per minute for tracking only
        self.server_send_fail = []
        self.cycle_time = 0

    # ---------------------------- Settings ------------------------------------
    @commands.group(pass_context=True)
    async def osuset(self, ctx):
        """Where you can define some settings"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)
            return

    @osuset.command(pass_context=True, no_pm=True)
    @checks.is_owner()
    async def tracktop(self, ctx, top_num:int):
        """ Set # of top plays being tracked """
        msg = ""
        if top_num < 1 or top_num > 100:
            msg = "**Please enter a valid number. (1 - 100)**"
        else:
            self.osu_settings["num_track"] = top_num
            msg = "**Maximum tracking set to {} plays.**".format(top_num)
            fileIO("data/osu/osu_settings.json", "save", self.osu_settings)
        await self.bot.say(msg)

    @osuset.command(pass_context=True, no_pm=True)
    @checks.is_owner()
    async def displaytop(self, ctx, top_num:int):
        """ Set # of best plays being displayed in top command """
        msg = ""
        if top_num < 1 or top_num > 10:
            msg = "**Please enter a valid number. (1 - 10)**"
        else:
            self.osu_settings["num_best_plays"] = top_num
            msg = "**Now Displaying Top {} Plays.**".format(top_num)
            fileIO("data/osu/osu_settings.json", "save", self.osu_settings)
        await self.bot.say(msg)

    @osuset.command(pass_context=True, no_pm=True)
    @checks.admin_or_permissions(manage_messages=True)
    async def tracking(self, ctx, toggle=None):
        """ For disabling tracking on server (enable/disable) """
        server = ctx.message.server

        server_settings = db.osu_settings.find_one({'server_id':server.id})
        if not server_settings:
            db.osu_settings.insert_one({'server_id':server.id})
            server_settings = db.osu_settings.find_one({'server_id':server.id})

        if 'tracking' not in server_settings:
            db.osu_settings.update_one({'server_id':server.id}, {'$set': {
                'tracking': True}})
        server_settings = db.osu_settings.find_one({'server_id':server.id})

        status = ""
        if not toggle:
            track = server_settings['tracking']
            if not track:
                track = True
                status = "Enabled"
            else:
                track = False
                status = "Disabled"
        elif toggle.lower() == "enable":
            track = True
            status = "Enabled"
        elif toggle.lower() == "disable":
            track = False
            status = "Disabled"
        db.osu_settings.update_one({'server_id':server.id}, {'$set': {'tracking': track}})
        await self.bot.say("**Player Tracking {} on {}.**".format(server.name, status))

    @commands.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def overview(self, ctx):
        """ Get an overview of your settings """
        server = ctx.message.server
        user = ctx.message.author

        em = discord.Embed(description='', colour=user.colour)
        em.set_author(name="Current Settings for {}".format(server.name), icon_url = server.icon_url)

        # determine api to use
        server_settings = db.osu_settings.find_one({'server_id':server.id})
        if server_settings:
            if "api" not in server_settings:
                api = "Official osu! API"
            elif server_settings["api"] == self.osu_settings["type"]["default"]:
                api = "Official osu! API"
            elif server_settings["api"] == self.osu_settings["type"]["ripple"]:
                api = "Ripple API"
        else:
            api = "Official osu! API"

        # determine
        if not server_settings or "tracking" not in server_settings or server_settings["tracking"] == True:
            tracking = "Enabled"
        else:
            tracking = "Disabled"

        info = ""
        info += "**▸ Default API:** {}\n".format(api)
        info += "**▸ Top Plays (Global):** {}\n".format(self.osu_settings['num_best_plays'])
        info += "**▸ Tracking:** {}\n".format(tracking)

        if tracking == "Enabled":
            info += "**▸ Tracking Max (Global):** {}\n".format(self.osu_settings['num_track'])
        info += "**▸ Tracking Total (Global):** {} players\n".format(str(db.track.count()))
        info += "**▸ Tracking Cycle Time:** {:.3f} min".format(float(self.cycle_time))

        em.description = info
        await self.bot.say(embed = em)

    @osuset.command(pass_context=True, no_pm=True)
    @checks.is_owner()
    async def api(self, ctx, *, choice):
        """'official' or 'ripple'"""
        server = ctx.message.server
        server_settings = db.osu_settings.find_one({'server_id':server.id})
        if not server_settings or 'api' not in server_settings:
            db.osu_settings.insert_one({'server_id':server.id, 'api':self.osu_settings["type"]["default"]})

        if not choice.lower() == "official" and not choice.lower() == "ripple":
            await self.bot.say("The two choices are `official` and `ripple`")
            return
        elif choice.lower() == "official":
            db.osu_settings.update_one({'server_id':server.id}, {'$set':{"api": self.osu_settings["type"]["default"]}})
        elif choice.lower() == "ripple":
            db.osu_settings.update_one({'server_id':server.id}, {'$set':{"api": self.osu_settings["type"]["ripple"]}})
        await self.bot.say("**Switched to `{}` server as default on `{}`.**".format(choice, server.name))

    @osuset.command(pass_context=True, no_pm=True)
    async def default(self, ctx, mode:str):
        """ Set your default gamemode """
        user = ctx.message.author
        server = ctx.message.server

        try:
            if mode.lower() in modes:
                gamemode = modes.index(mode.lower())
            elif int(mode) >= 0 and int(mode) <= 3:
                gamemode = int(mode)
            else:
                await self.bot.say("**Please enter a valid gamemode.**")
                return
        except:
            await self.bot.say("**Please enter a valid gamemode.**")
            return

        user_set = db.user_settings.find_one({'user_id':user.id})
        if user_set:
            db.user_settings.update_one({'user_id':user.id},
                {'$set':{"default_gamemode": int(gamemode)}})
            await self.bot.say("**`{}`'s default gamemode has been set to `{}`.** :white_check_mark:".format(user.name, modes[gamemode]))
        else:
            await self.bot.say(help_msg[1])

    @commands.group(pass_context=True)
    async def osutrack(self, ctx):
        """Where you can define some settings"""
        if ctx.invoked_subcommand is None:
            await send_cmd_help(ctx)
            return

    @osuset.command(pass_context=True)
    @checks.is_owner()
    async def key(self, ctx):
        """Sets your osu api key"""
        await self.bot.whisper("Type your osu! api key. You can reply here.")
        key = await self.bot.wait_for_message(timeout=30, author=ctx.message.author)
        if key is None:
            return
        else:
            self.osu_api_key["osu_api_key"] = key.content
            fileIO("data/osu/apikey.json", "save", self.osu_api_key)
            await self.bot.whisper("API Key details added. :white_check_mark:")

    @commands.command(pass_context=True, no_pm=True)
    async def osu(self, ctx, *username):
        """[p]osu usernames [-ripple|-official]"""
        await self._process_user_info(ctx, username, 0)

    @commands.command(pass_context=True, no_pm=True)
    async def osutop(self, ctx, *username):
        """[p]osutop username [-ripple|-official]"""
        await self._process_user_top(ctx, username, 0)

    @commands.command(pass_context=True, no_pm=True)
    async def taiko(self, ctx, *username):
        """[p]taiko usernames [-ripple|-official]"""
        await self._process_user_info(ctx, username, 1)

    @commands.command(pass_context=True, no_pm=True)
    async def taikotop(self, ctx, *username):
        """[p]taikotop username [-ripple|-official]"""
        await self._process_user_top(ctx, username, 1)

    @commands.command(pass_context=True, no_pm=True)
    async def ctb(self, ctx, *username):
        """[p]ctb usernames [-ripple|-official]"""
        await self._process_user_info(ctx, username, 2)

    @commands.command(pass_context=True, no_pm=True)
    async def ctbtop(self, ctx, *username):
        """[p]ctbtop username [-ripple|-official]"""
        await self._process_user_top(ctx, username, 2)

    @commands.command(pass_context=True, no_pm=True)
    async def mania(self, ctx, *username):
        """[p]mania usernames [-ripple|-official]"""
        await self._process_user_info(ctx, username, 3)

    @commands.command(pass_context=True, no_pm=True)
    async def maniatop(self, ctx, *username):
        """[p]maniatop username [-ripple|-official]"""
        await self._process_user_top(ctx, username, 3)

    @commands.command(pass_context=True, no_pm=True)
    async def recent(self, ctx, *username):
        """[p]recent username [gamemode] [-ripple|-official]"""
        await self._process_user_recent(ctx, username)

    @osuset.command(pass_context=True, no_pm=True)
    async def user(self, ctx, *, username):
        """Sets user information given an osu! username"""
        user = ctx.message.author
        channel = ctx.message.channel
        server = user.server
        key = self.osu_api_key["osu_api_key"]

        if not self._check_user_exists(user):
            try:
                osu_user = list(await get_user(key, self.osu_settings["type"]["default"], username, 1))
                newuser = {
                    "discord_username": user.name,
                    "osu_username": username,
                    "osu_user_id": osu_user[0]["user_id"],
                    "default_gamemode": 0,
                    "ripple_username": "",
                    "ripple_user_id": "",
                    "user_id": user.id
                }
                db.user_settings.insert_one(newuser)
                await self.bot.say("{}, your account has been linked to osu! username `{}`".format(user.mention, osu_user[0]["username"]))
            except:
                await self.bot.say("`{}` doesn't exist in the osu! database.".format(username))
        else:
            try:
                osu_user = list(await get_user(key, self.osu_settings["type"]["default"], username, 1))
                db.user_settings.update_one({'user_id': user.id}, {'$set':{'osu_username':username,
                    "osu_user_id":osu_user[0]["user_id"]
                    }})

                stevy_info = db.user_settings.find_one({'user_id':user.id})
                await self.bot.say("{}, your osu! username has been edited to `{}`".format(user.mention, osu_user[0]["username"]))
            except:
                await self.bot.say("`{}` doesn't exist in the osu! database.".format(username))

    @osuset.command(name = "skin", pass_context=True, no_pm=True)
    async def setskin(self, ctx, link:str):
        """Link your skin."""
        user = ctx.message.author
        user_set = db.user_settings.find_one({'user_id':user.id})
        if user_set != None:

            """ # Later
            if link == '-find':
                url = self._find_skin(user_set['osu_user_id'])
            elif self._is_valid_skin(link):
                url = link
            else:
                return"""

            db.user_settings.update_one({'user_id':user.id},
                {'$set':{"skin": link}})
            await self.bot.say("**`{}`'s skin has been set to `{}`.**".format(user.name, link))
        else:
            await self.bot.say(help_msg[1])

    @commands.command(pass_context=True, no_pm=True)
    async def skin(self, ctx, user:discord.Member = None):
        """[p]skin username"""
        if user == None:
            user = ctx.message.author

        userinfo = db.user_settings.find_one({'user_id':user.id})

        if userinfo != None:
            if 'skin' in userinfo:
                await self.bot.say("**`{}`'s Skin: <{}>.**".format(user.name, userinfo['skin']))
            else:
                await self.bot.say("**`{}` has not set a skin.**".format(user.name))
        else:
            await self.bot.say("**`{}` does not have an account linked.**".format(user.name))

    # Gets json information to proccess the small version of the image
    async def _process_user_info(self, ctx, usernames, gamemode:int):
        key = self.osu_api_key["osu_api_key"]
        channel = ctx.message.channel
        user = ctx.message.author
        server = user.server

        if not usernames:
            usernames = [None]
        # get rid of duplicates initially
        usernames = list(set(usernames))

        # determine api to use
        usernames, api = self._determine_api(server, usernames)

        # gives the final input for osu username
        final_usernames = []
        for username in usernames:
            test_username = await self._process_username(ctx, username)
            if test_username != None:
                final_usernames.append(test_username)

        # get rid of duplicates initially
        final_usernames = list(set(final_usernames))

        # testing if username is osu username
        all_user_info = []
        sequence = []

        count_valid = 0
        for i in range(len(final_usernames)):
            userinfo = list(await get_user(key, api, final_usernames[i], gamemode)) # get user info from osu api
            if userinfo != None and len(userinfo) > 0 and userinfo[0]['pp_raw'] != None:
                all_user_info.append(userinfo[0])
                sequence.append((count_valid, int(userinfo[0]["pp_rank"])))
                count_valid = count_valid + 1
            else:
                await self.bot.say("**`{}` has not played enough.**".format(final_usernames[i]))

        sequence = sorted(sequence, key=operator.itemgetter(1))

        all_players = []
        for i, pp in sequence:
            all_players.append(await self._get_user_info(api, server, user, all_user_info[i], gamemode))

        disp_num = min(self.num_max_prof, len(all_players))
        if disp_num < len(all_players):
            await self.bot.say("Found {} users, but displaying top {}.".format(len(all_players), disp_num))

        for player in all_players[0:disp_num]:
            await self.bot.say(embed=player)

    # takes iterable of inputs and determines api, also based on defaults
    def _determine_api(self, server, inputs):

        if not inputs or ('-ripple' not in inputs and '-official' not in inputs): # in case not specified
            server_settings = db.osu_settings.find_one({'server_id':server.id})
            if server_settings and "api" in server_settings:
                if server_settings["api"] == self.osu_settings["type"]["default"]:
                    api = self.osu_settings["type"]["default"]
                elif server_settings["api"] == self.osu_settings["type"]["ripple"]:
                    api = self.osu_settings["type"]["ripple"]
            else:
                api = self.osu_settings["type"]["default"]
        if '-ripple' in inputs:
            inputs = list(inputs)
            inputs.remove('-ripple')
            api = self.osu_settings["type"]["ripple"]
        if '-official' in inputs:
            inputs = list(inputs)
            inputs.remove('-official')
            api = self.osu_settings["type"]["default"]

        if not inputs:
            inputs = [None]

        return inputs, api

    # Gets the user's most recent score
    async def _process_user_recent(self, ctx, inputs):
        key = self.osu_api_key["osu_api_key"]
        channel = ctx.message.channel
        user = ctx.message.author
        server = user.server

        # forced handle gamemode
        gamemode = -1
        inputs = list(inputs)
        for mode in modes:
            if len(inputs) >= 2 and mode in inputs:
                gamemode = self._get_gamemode_number(mode)
                inputs.remove(mode)
            elif len(inputs) == 1 and mode == inputs[0]:
                gamemode = self._get_gamemode_number(mode)
                inputs.remove(mode)
        inputs = tuple(inputs)

        # handle api and username (1)
        username, api = self._determine_api(server, list(inputs))
        username = username[0]

        # gives the final input for osu username
        test_username = await self._process_username(ctx, username)
        if test_username:
            username = test_username
        else:
            return

        # determines which recent gamemode to display based on user
        if gamemode == -1:
            target_id = self._get_discord_id(username, api)
            if target_id != -1:
                user_setting = db.user_settings.find_one({'user_id':target_id})
                gamemode = user_setting['default_gamemode']
            elif target_id == -1 and self._check_user_exists(user):
                user_setting = db.user_settings.find_one({'user_id':user.id})
                gamemode = user_setting['default_gamemode']
            else:
                gamemode = 0

        # get userinfo
        userinfo = list(await get_user(key, api, username, gamemode))
        userrecent = list(await get_user_recent(key, api, username, gamemode))
        if not userinfo or not userrecent:
            await self.bot.say("**`{}` was not found or no recent plays in `{}`.**".format(username, self._get_gamemode(gamemode)))
            return
        else:
            userinfo = userinfo[0]
            userrecent = userrecent[0]
            msg, recent_play = await self._get_recent(ctx, api, userinfo, userrecent, gamemode)
            await self.bot.say(msg, embed=recent_play)

    def _get_discord_id(self, username:str, api:str):
        #if api == self.osu_settings["type"]["ripple"]:
            #name_type = "ripple_username"
        #else:
            #name_type = "osu_username"
        # currently assumes same name
        name_type = "osu_username"
        user = db.user_settings.find_one({name_type:username})
        if user:
            return user['user_id']
        return -1

    # Gets information to proccess the top play version of the image
    async def _process_user_top(self, ctx, username, gamemode: int):
        key = self.osu_api_key["osu_api_key"]
        channel = ctx.message.channel
        user = ctx.message.author
        server = user.server

        # Written by Jams
        score_num = -1
        if '-p' in username:
            marker_loc = username.index('-p')
            if len(username) - 1 == marker_loc:
                await self.bot.say("**Please provide a score number!**")
                return

            username = tuple(username)
            score_num = username[marker_loc + 1]
            if not score_num.isdigit():
                await self.bot.say("**Please use only whole numbers for number of top plays!**")
                return
            else:
                score_num = int(score_num)

            if score_num <= 0 or score_num > 100:
                await self.bot.say("**Please enter a valid top play number! (1-100)**")
                return

            username = list(username)
            del username[marker_loc + 1]
            del username[marker_loc]

        # determine api to use
        username, api = self._determine_api(server, list(username))

        if score_num == -1:
            username = username[0]

            # gives the final input for osu username
            username = await self._process_username(ctx, username)

            # for getting top plays
            userinfo = list(await get_user(key, api, username, gamemode))
            userbest = list(await get_user_best(
                key, api, username, gamemode, self.osu_settings['num_best_plays']))
            if userinfo and userbest:
                msg, top_plays = await self._get_user_top(ctx, api, userinfo[0], userbest, gamemode)
                await self.bot.say(msg, embed=top_plays)
            else:
                await self.bot.say("**`{}` was not found or not enough plays.**".format(username))
        else:
            usernames = list(username)
            sorted_order = []
            # get all the plays
            for username in usernames:
                username = await self._process_username(ctx, username)
                # for a specific score in top 100
                userinfo = list(await get_user(key, api, username, gamemode))
                userbest = list(await get_user_best(key, api, username, gamemode, score_num))
                # check if user has enough scores for that number
                if not score_num <= len(userbest):
                    await self.bot.say("**`{}` does not have enough plays.**".format(username))
                elif userinfo and userbest:
                    msg, score_play = await self._get_top_num(
                        ctx, api, userinfo[0], userbest, score_num, gamemode)
                    sorted_order.append((userbest[int(score_num-1)]['pp'], score_play))
                else:
                    await self.bot.say("**`{}` was not found or not enough plays.**".format(username))

            # order them by pp
            sorted_order = sorted(sorted_order, key=operator.itemgetter(0), reverse=True)
            for pp, embed_play in sorted_order[:5]:
                await self.bot.say('', embed=embed_play)

    ## processes username. probably the worst chunck of code in this project so far. will fix/clean later
    async def _process_username(self, ctx, username):
        channel = ctx.message.channel
        user = ctx.message.author
        server = user.server
        key = self.osu_api_key["osu_api_key"]

        # if nothing is given, must rely on if there's account
        if not username:
            if self._check_user_exists(user):
                find_user = db.user_settings.find_one({"user_id":user.id})
                username = find_user["osu_username"]
            else:
                await self.bot.say("It doesn't seem that you have an account linked. Do `{}osuset user [username]`.".format(prefix))
                return None # bad practice, but too lazy to make it nice
        # if it's a discord user, first check to see if they are in database and choose that username
        # then see if the discord username is a osu username, then try the string itself
        elif find(lambda m: m.name == username, channel.server.members) is not None:
            target = find(lambda m: m.name == username, channel.server.members)
            try:
                find_user = db.user_settings.find_one({"user_id":target.id})
                username = find_user["osu_username"]
            except:
                if await get_user(key, self.osu_settings["type"]["default"], username, 0):
                    username = str(target)
                else:
                    await self.bot.say(help_msg[1])
                    return
        # @ implies its a discord user (if not, it will just say user not found in the next section)
        # if not found, then oh well.
        elif "@" in username:
            user_id = re.findall("\d+", username)
            if user_id:
                user_id = user_id[0]
                find_user = db.user_settings.find_one({"user_id":user_id})
                if find_user:
                    username = find_user["osu_username"]
                else:
                    await self.bot.say(help_msg[1])
                    return
            else:
                await self.bot.say(help_msg[1])
                return
        else:
            username = str(username)
        return username

    # Checks if user exists
    def _check_user_exists(self, user):
        find_user = db.user_settings.find_one({"user_id":user.id})
        if not find_user:
            return False
        return True

    def _get_api_name(self, url:str):
        if url == self.osu_settings["type"]["ripple"]:
            return "Ripple"
        else:
            return "Official"

    # Gives a small user profile
    async def _get_user_info(self, api:str, server, server_user, user, gamemode: int):
        if api == self.osu_settings["type"]["default"]:
            profile_url ='https://a.ppy.sh/{}'.format(user['user_id'])
            pp_country_rank = " ({}#{})".format(user['country'], user['pp_country_rank'])
        elif api == self.osu_settings["type"]["ripple"]:
            profile_url = 'http://a.ripple.moe/{}.png'.format(user['user_id'])
            pp_country_rank = ""

        flag_url = 'https://osu.ppy.sh/images/flags/{}.png'.format(user['country'])

        gamemode_text = self._get_gamemode(gamemode)

        #try:
        user_url = 'https://{}/u/{}'.format(api, user['user_id'])
        em = discord.Embed(description='', colour=server_user.colour)
        em.set_author(name="{} Profile for {}".format(gamemode_text, user['username']), icon_url = flag_url, url = user_url)
        em.set_thumbnail(url=profile_url)
        level_int = int(float(user['level']))
        level_percent = float(user['level']) - level_int

        info = ""
        info += "**▸ {} Rank:** #{} {}\n".format(self._get_api_name(api), user['pp_rank'], pp_country_rank)
        info += "**▸ Level:** {} ({:.2f}%)\n".format(level_int, level_percent*100)
        info += "**▸ Total PP:** {}\n".format(user['pp_raw'])
        info += "**▸ Hit Accuracy:** {}%\n".format(user['accuracy'][0:5])
        info += "**▸ Playcount:** {}".format(user['playcount'])
        em.description = info

        if api == self.osu_settings["type"]["default"]:
            soup = BeautifulSoup(urllib.request.urlopen("https://osu.ppy.sh/u/{}".format(user['user_id'])), "html.parser")
            timestamps = []
            for tag in soup.findAll(attrs={'class': 'timeago'}):
                timestamps.append(datetime.datetime.strptime(tag.contents[0].strip().replace(" UTC", ""), '%Y-%m-%d %H:%M:%S'))
            timeago = self._time_ago(datetime.datetime.now(), timestamps[1])
            time_ago = "Last Logged in {} ago".format(timeago)
            em.set_footer(text=time_ago)
        else:
            em.set_footer(text = "On osu! {} Server".format(self._get_api_name(api)))

        return em
        #except:
            #return None

    async def _get_recent(self, ctx, api, user, userrecent, gamemode:int):
        server_user = ctx.message.author
        server = ctx.message.server
        key = self.osu_api_key["osu_api_key"]

        if api == self.osu_settings["type"]["default"]:
            profile_url ='https://a.ppy.sh/{}'.format(user['user_id'])
        elif api == self.osu_settings["type"]["ripple"]:
            profile_url = 'http://a.ripple.moe/{}.png'.format(user['user_id'])

        flag_url = 'https://osu.ppy.sh/images/flags/{}.png'.format(user['country'])

        # get best plays map information and scores
        beatmap = list(await get_beatmap(key, api, beatmap_id=userrecent['beatmap_id']))[0]
        if not userrecent:
            return ("**No recent score for `{}` in user's default gamemode (`{}`)**".format(user['username'], self._get_gamemode(gamemode)), None)
        acc = self.calculate_acc(userrecent, gamemode)
        fc_acc = self.no_choke_acc(userrecent, gamemode)
        mods = self.num_to_mod(userrecent['enabled_mods'])

        # determine mods
        if not mods:
            mods = []
            mods.append('No Mod')
        else:
            oppai_mods = "+{}".format("".join(mods))

        beatmap_url = 'https://osu.ppy.sh/b/{}'.format(beatmap['beatmap_id'])

        msg = "**Most Recent {} Play for {}:**".format(self._get_gamemode(gamemode), user['username'])
        info = ""

        # calculate potential pp
        pot_pp = ''
        if userrecent['rank'] == 'F':
            totalhits = (int(userrecent['count50']) + int(userrecent['count100']) + int(userrecent['count300']) + int(userrecent['countmiss']))
            oppai_output = get_pyoppai(userrecent['beatmap_id'], accs=[float(acc)], mods = int(userrecent['enabled_mods']), completion=totalhits, misses=int(userrecent['countmiss']))
            if oppai_output != None:
                pot_pp = '**No PP** ({:.2f}PP for FC)'.format(oppai_output['pp'][0])
        else:
            oppai_output = get_pyoppai(userrecent['beatmap_id'], combo=int(userrecent['maxcombo']), accs=[float(acc)], fc=fc_acc, mods = int(userrecent['enabled_mods']), misses=int(userrecent['countmiss']))
            if oppai_output != None:
                pot_pp = '**{:.2f}PP** ({:.2f}PP for FC)'.format(oppai_output['pp'][0], oppai_output['pp'][1])

        info += "▸ **{} Rank** ▸ {} ▸ {}%\n".format(userrecent['rank'], pot_pp, round(acc,2))
        info += "▸ {} ▸ x{}/{} ▸ [{}/{}/{}/{}]\n".format(
            userrecent['score'],
            userrecent['maxcombo'], beatmap['max_combo'],
            userrecent['count300'], userrecent['count100'], userrecent['count50'], userrecent['countmiss'])
        if userrecent['rank'] == 'F':
            try:
                info += "▸ **Map Completion:** {:.2f}%".format(oppai_output['map_completion'])
            except:
                pass

        # grab beatmap image
        page = urllib.request.urlopen(beatmap_url)
        soup = BeautifulSoup(page.read(), "html.parser")
        map_image = [x['src'] for x in soup.findAll('img', {'class': 'bmt'})] # just in case yaknow
        map_image_url = 'http:{}'.format(map_image[0]).replace(" ","%")

        em = discord.Embed(description=info, colour=server_user.colour)
        em.set_author(name="{} [{}] +{} [{}★]".format(beatmap['title'], beatmap['version'],
            self._fix_mods(''.join(mods)),
            self._compare_val(beatmap['difficultyrating'], oppai_output, 'stars', dec_places = 2, single = True)), url = beatmap_url, icon_url = profile_url)
        em.set_thumbnail(url=map_image_url)
        time_ago = self._time_ago(datetime.datetime.utcnow() + datetime.timedelta(hours=8), datetime.datetime.strptime(userrecent['date'], '%Y-%m-%d %H:%M:%S'))
        em.set_footer(text = "{}Ago On osu! {} Server".format(time_ago, self._get_api_name(api)))
        return (msg, em)

    # Gives a user profile image with some information
    async def _get_user_top(self, ctx, api, user, userbest, gamemode:int):
        server_user = ctx.message.author
        server = ctx.message.server
        key = self.osu_api_key["osu_api_key"]

        if api == self.osu_settings["type"]["default"]:
            profile_url ='https://a.ppy.sh/{}'.format(user['user_id'])
        elif api == self.osu_settings["type"]["ripple"]:
            profile_url = 'http://a.ripple.moe/{}.png'.format(user['user_id'])

        flag_url = 'https://osu.ppy.sh/images/flags/{}.png'.format(user['country'])
        gamemode_text = self._get_gamemode(gamemode)

        # get best plays map information and scores
        best_beatmaps = []
        best_acc = []
        for i in range(self.osu_settings['num_best_plays']):
            beatmap = list(await get_beatmap(key, api, beatmap_id=userbest[i]['beatmap_id']))[0]
            score = list(await get_scores(key, api, userbest[i]['beatmap_id'], user['user_id'], gamemode))[0]
            best_beatmaps.append(beatmap)
            best_acc.append(self.calculate_acc(score,gamemode))

        all_plays = []
        msg = ""
        desc = ''
        for i in range(self.osu_settings['num_best_plays']):
            mods = self.num_to_mod(userbest[i]['enabled_mods'])
            oppai_info = get_pyoppai(best_beatmaps[i]['beatmap_id'], accs = [float(best_acc[i])], mods = int(userbest[i]['enabled_mods']))

            if not mods:
                mods = []
                mods.append('No Mod')
            beatmap_url = 'https://osu.ppy.sh/b/{}'.format(best_beatmaps[i]['beatmap_id'])

            info = ''
            info += '**{}. [{} [{}]]({}) +{}** [{}★]\n'.format(
                i+1, best_beatmaps[i]['title'],
                best_beatmaps[i]['version'], beatmap_url,
                self._fix_mods(''.join(mods)),
                self._compare_val(best_beatmaps[i]['difficultyrating'], oppai_info, param = 'stars', dec_places = 2, single = True))
            # choke text
            choke_text = ''
            if (oppai_info != None and userbest[i]['countmiss'] != None and best_beatmaps[i]['max_combo']!= None) and (int(userbest[i]['countmiss'])>=1 or (int(userbest[i]['maxcombo']) <= 0.95*int(best_beatmaps[i]['max_combo']) and 'S' in userbest[i]['rank'])):
                choke_text += ' _({:.2f}pp for FC)_'.format(oppai_info['pp'][0])
            info += '▸ **{} Rank** ▸ **{:.2f}pp**{} ▸ {:.2f}%\n'.format(userbest[i]['rank'], float(userbest[i]['pp']), choke_text, float(best_acc[i]))
            info += '▸ {} ▸ x{}/{} ▸ [{}/{}/{}/{}]\n'.format(
                userbest[i]['score'],
                userbest[i]['maxcombo'], best_beatmaps[i]['max_combo'],
                userbest[i]['count300'],userbest[i]['count100'],userbest[i]['count50'],userbest[i]['countmiss']
                )

            time_ago = self._time_ago(datetime.datetime.utcnow() + datetime.timedelta(hours=8), datetime.datetime.strptime(userbest[i]['date'], '%Y-%m-%d %H:%M:%S'))
            info += '▸ Score Set {}Ago\n'.format(time_ago)

            desc += info
        em = discord.Embed(description=desc, colour=server_user.colour)
        title = "Top {} {} Plays for {}".format(self.osu_settings['num_best_plays'], gamemode_text, user['username'])
        em.set_author(name = title, url="https://osu.ppy.sh/u/{}".format(user['user_id']), icon_url=flag_url)
        em.set_footer(text = "On osu! {} Server".format(self._get_api_name(api)))
        em.set_thumbnail(url=profile_url)

        return (msg, em)

    # written by Jams
    async def _get_top_num(self, ctx, api, user, userbest, num_score, gamemode:int):
        server_user = ctx.message.author
        server = ctx.message.server
        key = self.osu_api_key["osu_api_key"]

        if api == self.osu_settings["type"]["default"]:
            profile_url = 'http://s.ppy.sh/a/{}.png'.format(user['user_id'])
        elif api == self.osu_settings["type"]["ripple"]:
            profile_url = 'http://a.ripple.moe/{}.png'.format(user['user_id'])

        flag_url = 'https://new.ppy.sh//images/flags/{}.png'.format(user['country'])
        gamemode_text = self._get_gamemode(gamemode)

        # get best plays map information and scores
        num_score = int(num_score) - 1
        beatmap = list(await get_beatmap(key, api, beatmap_id=userbest[num_score]['beatmap_id']))[0]
        score = list(await get_scores(key, api, userbest[num_score]['beatmap_id'], user['user_id'], gamemode))[0]
        best_beatmaps = [beatmap]
        best_acc = [self.calculate_acc(score,gamemode)]

        msg = "**{}'s #{} Top {} Play on {} server:**".format(user['username'], num_score+1, gamemode_text, self._get_api_name(api))
        title = best_beatmaps[0]['title']
        if '*' in title:
            title = title.replace('*', ' ')
        mods = self.num_to_mod(userbest[num_score]['enabled_mods'])
        if not mods:
            mods = ['No Mod']
        beatmap_url = 'https://osu.ppy.sh/b/{}'.format(best_beatmaps[0]['beatmap_id'])

        mods = self.num_to_mod(userbest[num_score]['enabled_mods'])
        oppai_info = get_pyoppai(best_beatmaps[0]['beatmap_id'], accs = [float(best_acc[0])], mods = int(userbest[num_score]['enabled_mods']))

        if not mods:
            mods = []
            mods.append('No Mod')
        beatmap_url = 'https://osu.ppy.sh/b/{}'.format(best_beatmaps[0]['beatmap_id'])

        info = ''
        info += '**[{} [{}]]({}) +{}** [{}★]\n'.format(
            best_beatmaps[0]['title'],
            best_beatmaps[0]['version'], beatmap_url,
            self._fix_mods(''.join(mods)),
            self._compare_val(best_beatmaps[0]['difficultyrating'], oppai_info, param = 'stars', dec_places = 2, single = True))
        # choke text
        choke_text = ''
        if (oppai_info != None and userbest[num_score]['countmiss'] != None and best_beatmaps[0]['max_combo']!= None) and (int(userbest[num_score]['countmiss'])>=1 or (int(userbest[num_score]['maxcombo']) <= 0.95*int(best_beatmaps[0]['max_combo']) and 'S' in userbest[num_score]['rank'])):
            choke_text += ' _({:.2f}pp for FC)_'.format(oppai_info['pp'][0])
        info += '▸ **{} Rank** ▸ **{:.2f}pp**{} ▸ {:.2f}%\n'.format(userbest[num_score]['rank'], float(userbest[num_score]['pp']), choke_text, float(best_acc[0]))
        info += '▸ {} ▸ x{}/{} ▸ [{}/{}/{}/{}]\n'.format(
            userbest[num_score]['score'],
            userbest[num_score]['maxcombo'], best_beatmaps[0]['max_combo'],
            userbest[num_score]['count300'],userbest[num_score]['count100'],userbest[num_score]['count50'],userbest[num_score]['countmiss']
            )

        time_ago = self._time_ago(datetime.datetime.utcnow() + datetime.timedelta(hours=8), datetime.datetime.strptime(userbest[num_score]['date'], '%Y-%m-%d %H:%M:%S'))
        info += '▸ Score Set {}Ago\n'.format(time_ago)

        em = discord.Embed(description=info, colour=server_user.colour)
        title = "Top {} {} Play for {}".format(num_score+1, gamemode_text, user['username'])
        em.set_author(name = title, url="https://osu.ppy.sh/u/{}".format(user['user_id']), icon_url=flag_url)
        em.set_footer(text = "On osu! {} Server".format(self._get_api_name(api)))
        em.set_thumbnail(url=profile_url)

        return (msg, em)

    # because you people just won't stop bothering me about it
    def _fix_mods(self, mods:str):
        if mods == 'PFSOFLNCHTRXDTSDHRHDEZNF':
            return '? KEY'
        else:
            return mods.replace('DTHRHD', 'HDHRDT').replace('DTHD','HDDT').replace('HRHD', 'HDHR')

    def _get_gamemode(self, gamemode:int):
        if gamemode == 1:
            gamemode_text = "Taiko"
        elif gamemode == 2:
            gamemode_text = "Catch the Beat!"
        elif gamemode == 3:
            gamemode_text = "osu! Mania"
        else:
            gamemode_text = "osu! Standard"
        return gamemode_text

    def _get_gamemode_display(self, gamemode):
        if gamemode == "osu":
            gamemode_text = "osu! Standard"
        elif gamemode == "ctb":
            gamemode_text = "Catch the Beat!"
        elif gamemode == "mania":
            gamemode_text = "osu! Mania"
        elif gamemode == "taiko":
            gamemode_text = "Taiko"
        return gamemode_text

    def _get_gamemode_number(self, gamemode:str):
        if gamemode == "taiko":
            gamemode_text = 1
        elif gamemode == "ctb":
            gamemode_text = 2
        elif gamemode == "mania":
            gamemode_text = 3
        else:
            gamemode_text = 0
        return int(gamemode_text)

    def calculate_acc(self, beatmap, gamemode:int):
        if gamemode == 0:
            total_unscale_score = float(beatmap['count300'])
            total_unscale_score += float(beatmap['count100'])
            total_unscale_score += float(beatmap['count50'])
            total_unscale_score += float(beatmap['countmiss'])
            total_unscale_score *=300
            user_score = float(beatmap['count300']) * 300.0
            user_score += float(beatmap['count100']) * 100.0
            user_score += float(beatmap['count50']) * 50.0
        elif gamemode == 1:
            total_unscale_score = float(beatmap['count300'])
            total_unscale_score += float(beatmap['count100'])
            total_unscale_score += float(beatmap['countmiss'])
            total_unscale_score *= 300
            user_score = float(beatmap['count300']) * 1.0
            user_score += float(beatmap['count100']) * 0.5
            user_score *= 300
        elif gamemode == 2:
            total_unscale_score = float(beatmap['count300'])
            total_unscale_score += float(beatmap['count100'])
            total_unscale_score += float(beatmap['count50'])
            total_unscale_score += float(beatmap['countmiss'])
            total_unscale_score += float(beatmap['countkatu'])
            user_score = float(beatmap['count300'])
            user_score += float(beatmap['count100'])
            user_score  += float(beatmap['count50'])
        elif gamemode == 3:
            total_unscale_score = float(beatmap['count300'])
            total_unscale_score += float(beatmap['countgeki'])
            total_unscale_score += float(beatmap['countkatu'])
            total_unscale_score += float(beatmap['count100'])
            total_unscale_score += float(beatmap['count50'])
            total_unscale_score += float(beatmap['countmiss'])
            total_unscale_score *=300
            user_score = float(beatmap['count300']) * 300.0
            user_score += float(beatmap['countgeki']) * 300.0
            user_score += float(beatmap['countkatu']) * 200.0
            user_score += float(beatmap['count100']) * 100.0
            user_score += float(beatmap['count50']) * 50.0

        return (float(user_score)/float(total_unscale_score)) * 100.0

    def no_choke_acc(self, beatmap, gamemode:int):
        if gamemode == 0:
            total_unscale_score = float(beatmap['count300'])
            total_unscale_score += float(beatmap['count100'])
            total_unscale_score += float(beatmap['count50'])
            total_unscale_score += float(beatmap['countmiss'])
            total_unscale_score *=300
            user_score = float(beatmap['count300']) * 300.0
            user_score += (float(beatmap['count100']) + float(beatmap['countmiss'])) * 100.0
            user_score += float(beatmap['count50']) * 50.0
        elif gamemode == 1:
            total_unscale_score = float(beatmap['count300'])
            total_unscale_score += float(beatmap['count100'])
            total_unscale_score += float(beatmap['countmiss'])
            total_unscale_score *= 300
            user_score = float(beatmap['count300']) * 1.0
            user_score += (float(beatmap['count100']) + float(beatmap['countmiss'])) * 0.5
            user_score *= 300
        elif gamemode == 2:
            total_unscale_score = float(beatmap['count300'])
            total_unscale_score += float(beatmap['count100'])
            total_unscale_score += float(beatmap['count50'])
            total_unscale_score += float(beatmap['countmiss'])
            total_unscale_score += float(beatmap['countkatu'])
            user_score = float(beatmap['count300'])
            user_score += (float(beatmap['count100']) + float(beatmap['countmiss']))
            user_score  += float(beatmap['count50'])
        elif gamemode == 3:
            total_unscale_score = float(beatmap['count300'])
            total_unscale_score += float(beatmap['countgeki'])
            total_unscale_score += float(beatmap['countkatu'])
            total_unscale_score += float(beatmap['count100'])
            total_unscale_score += float(beatmap['count50'])
            total_unscale_score += float(beatmap['countmiss'])
            total_unscale_score *=300
            user_score = float(beatmap['count300']) * 300.0
            user_score += float(beatmap['countgeki']) * 300.0
            user_score += float(beatmap['countkatu']) * 200.0
            user_score += (float(beatmap['count100']) + float(beatmap['countmiss'])) * 100.0
            user_score += float(beatmap['count50']) * 50.0

        return (float(user_score)/float(total_unscale_score)) * 100.0

    # Truncates the text because some titles/versions are too long
    def truncate_text(self, text):
        if len(text) > 20:
            text = text[0:20] + '...'
        return text

    # gives a list of the ranked mods given a peppy number lol
    def num_to_mod(self, number):
        number = int(number)
        mod_list = []

        if number >= 16384:
            number -= 16384
            mod_list.append('PF')
        if number >= 4096:
            number-= 4096
            mod_list.append('SO')
        if number >= 1024:
            number-= 1024
            mod_list.append('FL')
        if number >= 576:
            number-= 576
            mod_list.append('NC')
        if number >= 256:
            number-= 256
            mod_list.append('HT')
        if number >= 128:
            number-= 128
            mod_list.append('RX')
        if number >= 64:
            number-= 64
            mod_list.append('DT')
        if number >= 32:
            number-= 32
            mod_list.append('SD')
        if number >= 16:
            number-= 16
            mod_list.append('HR')
        if number >= 8:
            number-= 8
            mod_list.append('HD')
        if number >= 2:
            number-= 2
            mod_list.append('EZ')
        if number >= 1:
            number-= 1
            mod_list.append('NF')
        return mod_list

    def mod_to_num(self, mods:str):
        mods = mods.upper()
        total = 0

        if 'PF' in mods:
            total += 16384
        if 'SO' in mods:
            total += 4096
        if 'FL' in mods:
            total += 1024
        if 'NC' in mods:
            total += 576
        elif 'DT' in mods:
            total += 64
        if 'HT' in mods:
            total += 256
        if 'RX' in mods:
            total += 128
        if 'SD' in mods:
            total += 32
        if 'HR' in mods:
            total += 16
        if 'HD' in mods:
            total += 8
        if 'EZ' in mods:
            total += 2
        if 'NF' in mods:
            total += 1

        return int(total)

    # ---------------------------- Detect Links ------------------------------
    # called by listener
    async def find_link(self, message):
        # await self.bot.send_message(message.channel, 'URL DETECTED')
        #try:
        if message.author.id == self.bot.user.id:
            return

        if "https://" in message.content:
            # process the the idea from a url in msg
            all_urls = []
            original_message = message.content
            get_urls = re.findall("(https:\/\/osu[^\s]+)([ ]\+[A-Za-z][^\s]+)?", original_message)

            for url in get_urls:
                all_urls.append(url)

            # get rid of duplicates
            all_urls = list(set(all_urls))

            if len(all_urls) > 3:
                print(all_urls)
                all_urls = all_urls[0:3]
                await self.bot.send_message(message.channel, "Too many links, processing first 3.")

            if 'https://osu.ppy.sh/u/' in original_message:
                await self.process_user_url(all_urls, message)

            if 'https://osu.ppy.sh/s/' in original_message or 'https://osu.ppy.sh/b/' in original_message:
                await self.process_beatmap(all_urls, message)
        #except:
            #pass

    # processes user input for user profile link
    async def process_user_url(self, all_urls, message):
        key = self.osu_api_key["osu_api_key"]
        server_user = message.author
        server = message.author.server

        for url, suffix in all_urls:
            try:
                if url.find('https://osu.ppy.sh/u/') != -1:
                    user_id = url.replace('https://osu.ppy.sh/u/','')
                    user_info = await get_user(
                        key, self.osu_settings["type"]["default"], user_id, 0)
                    find_user = db.user_settings.find_one({"user_id":user_id})
                    if find_user:
                        gamemode = int(find_user["default_gamemode"])
                    else:
                        gamemode = 0
                    em = await self._get_user_info(
                        self.osu_settings["type"]["default"],
                        server, server_user, user_info[0], gamemode)
                    await self.bot.send_message(message.channel, embed = em)
            except:
                pass

    # processes user input for the beatmap
    async def process_beatmap(self, all_urls, message):
        key = self.osu_api_key["osu_api_key"]

        for url, mods in all_urls:
            #try:
            if url.find('https://osu.ppy.sh/s/') != -1:
                beatmap_id = url.replace('https://osu.ppy.sh/s/','')
                beatmap_info = await get_beatmapset(key, self.osu_settings["type"]["default"], beatmap_id)
            elif url.find('https://osu.ppy.sh/b/') != -1:
                beatmap_id = url.replace('https://osu.ppy.sh/b/','')
                # find mods
                beatmap_info = await get_beatmap(key, self.osu_settings["type"]["default"], beatmap_id)
            await self.disp_beatmap(message, beatmap_info, url, mods)
            #except:
                #pass

    def _compare_val(self, map_stat, omap, param, dec_places:int = 1, single = False):
        if not omap:
            return "{}".format(round(float(map_stat), dec_places))
        else:
            map_stat = float(map_stat)
            op_stat = float(omap[param])
            if int(round(op_stat, dec_places)) != 0 and abs(round(map_stat, dec_places) - round(op_stat, dec_places)) > 0.05:
                if single:
                    return "{}".format(round(op_stat, dec_places))
                else:
                    return "{}({})".format(round(map_stat, dec_places),
                        round(op_stat, dec_places))
            else:
                return "{}".format(round(map_stat, dec_places))

    def _calc_time(self, total_sec, bpm, factor:float=1):
        m1, s1 = divmod(round(float(total_sec)/factor), 60)
        bpm1 = round(factor*float(bpm), 1)
        return (m1,s1,bpm1)

    # displays the beatmap properly
    async def disp_beatmap(self, message, beatmap, beatmap_url:str, mods=''):

        # create embed
        em = discord.Embed()

        # process time
        num_disp = min(len(beatmap), self.max_map_disp)
        if (len(beatmap) > self.max_map_disp):
            msg = "Found {} maps, but only displaying {}.\n".format(len(beatmap), self.max_map_disp)
        else:
            msg = "Found {} map(s).\n".format(len(beatmap))

        # sort by difficulty first
        map_order = []
        for i in range(len(beatmap)):
            map_order.append((i,float(beatmap[i]['difficultyrating'])))
        map_order = sorted(map_order, key=operator.itemgetter(1), reverse=True)
        map_order = map_order[0:num_disp]

        beatmap_msg = ""
        oppai_version = ""
        accs = [95, 99, 100]
        mods = mods.upper()
        mod_num = self.mod_to_num(mods)
        oppai_info = get_pyoppai(beatmap[0]['beatmap_id'], accs = accs, mods = mod_num) # def get_pyoppai(url:str, accs=[100], mods=0, misses=0, combo=None):

        m0, s0 = divmod(int(beatmap[0]['total_length']), 60)
        if oppai_info != None:
            # oppai_version = oppai_info['oppai_version']
            if 'DT' in mods or 'HT' in mods:
                if 'DT' in mods:
                    m1, s1, bpm_mod = self._calc_time(beatmap[0]['total_length'], beatmap[0]['bpm'], 1.5)
                elif 'HT' in mods:
                    m1, s1, bpm_mod = self._calc_time(beatmap[0]['total_length'], beatmap[0]['bpm'], (2/3))
                desc = '**Length:** {}:{}({}:{})  **BPM:** {:.1f}({}) '.format(
                    m0, str(s0).zfill(2),
                    m1, str(s1).zfill(2),
                    float(beatmap[0]['bpm']), bpm_mod)
            else:
                desc = '**Length:** {}:{} **BPM:** {}  '.format(m0,
                    str(s0).zfill(2), beatmap[0]['bpm'])
        else:
            desc = '**Length:** {}:{} **BPM:** {}  '.format(m0,
                str(s0).zfill(2), beatmap[0]['bpm'])

        # Handle mods
        desc += "**Mods:** "
        if mods != '':
            desc += mods
        else:
            desc += '-'
        desc += '\n'

        for i, diff in map_order:
            if i == 0:
                temp_oppai_info = oppai_info
            elif oppai_info == None:
                temp_oppai_info == None
            else:
                temp_oppai_info = get_pyoppai(beatmap[i]['beatmap_id'], accs = accs, mods = mod_num)

            beatmap_info = ""
            beatmap_info += "**▸Difficulty:** {}★ **▸Max Combo:** x{}\n".format(
                self._compare_val(beatmap[i]['difficultyrating'], temp_oppai_info, param = 'stars', dec_places = 2),
                beatmap[i]['max_combo'])
            beatmap_info += "**▸AR:** {} **▸OD:** {} **▸HP:** {} **▸CS:** {}\n".format(
                self._compare_val(beatmap[i]['diff_approach'], temp_oppai_info, param = 'ar'),
                self._compare_val(beatmap[i]['diff_overall'], temp_oppai_info, param = 'od'),
                self._compare_val(beatmap[i]['diff_drain'], temp_oppai_info, param = 'hp'),
                self._compare_val(beatmap[i]['diff_size'], temp_oppai_info, param = 'cs'))

            # calculate pp values
            if temp_oppai_info != None:
                beatmap_info += '**▸PP:** '
                for j in range(len(accs)):
                    beatmap_info += '○ **{}%**–{:.2f} '.format(accs[j], temp_oppai_info['pp'][j])

            em.add_field(name = "__{}__\n".format(beatmap[i]['version']), value = beatmap_info, inline = False)

        # handle excessive tags
        tags = beatmap[0]['tags']
        tags = tags.split(' ')
        max_tags = min(len(tags), 15)
        if max_tags < len(tags):
            tags = tags[0:14]
        tags = " ".join(tags)
        if tags == "":
            tags = "-"
        desc += '**Tags:** {}\n'.format(tags)
        desc += '-------------------'

        # determine color of embed based on status
        colour = self._determine_status_color(int(beatmap[i]['approved']))

        # create return em
        em.colour = colour
        em.description = desc
        em.set_author(name="{} – {} by {}".format(beatmap[0]['artist'], beatmap[0]['title'], beatmap[0]['creator']), url=beatmap_url)
        page = urllib.request.urlopen(beatmap_url)
        soup = BeautifulSoup(page.read(), "html.parser")
        map_image = [x['src'] for x in soup.findAll('img', {'class': 'bmt'})]
        map_image_url = 'http:{}'.format(map_image[0]).replace(" ", "%")
        # await self.bot.send_message(message.channel, map_image_url)
        em.set_thumbnail(url=map_image_url)

        if oppai_version != None:
            em.set_footer(text = 'Powered by Oppai v0.9.5'.format(oppai_version))

        await self.bot.send_message(message.channel, msg, embed = em)

    def _determine_status_color(self, status):
        colour = 0xFFFFFF

        if status == -2: # graveyard, red
            colour = 0xc10d0d
        elif status == -1: # WIP, purple
            colour = 0x713c93
        elif status == 0: # pending, blue
            colour = 0x1466cc
        elif status == 1: # ranked, bright green
            colour = 0x02cc37
        elif status == 2: # approved, dark green
            colour = 0x0f8c4a
        elif status == 3: # qualified, turqoise
            colour = 0x00cebd
        elif status == 4: # loved, pink
            colour = 0xea04e6

        return colour

    def _time_ago(self, time1, time2):
        time_diff = time1 - time2
        timeago = datetime.datetime(1,1,1) + time_diff
        time_limit = 0
        time_ago = ""
        if timeago.year-1 != 0:
            time_ago += "{} Year{} ".format(timeago.year-1, self._determine_plural(timeago.year-1))
            time_limit = time_limit + 1
        if timeago.month-1 !=0:
            time_ago += "{} Month{} ".format(timeago.month-1, self._determine_plural(timeago.month-1))
            time_limit = time_limit + 1
        if timeago.day-1 !=0 and not time_limit == 2:
            time_ago += "{} Day{} ".format(timeago.day-1, self._determine_plural(timeago.day-1))
            time_limit = time_limit + 1
        if timeago.hour != 0 and not time_limit == 2:
            time_ago += "{} Hour{} ".format(timeago.hour, self._determine_plural(timeago.hour))
            time_limit = time_limit + 1
        if timeago.minute != 0 and not time_limit == 2:
            time_ago += "{} Minute{} ".format(timeago.minute, self._determine_plural(timeago.minute))
            time_limit = time_limit + 1
        if not time_limit == 2:
            time_ago += "{} Second{} ".format(timeago.second, self._determine_plural(timeago.second))
        return time_ago

    # really stevy? yes, really.
    def _determine_plural(self, number):
        if int(number) != 1:
            return 's'
        else:
            return ''

    # --------------------- Tracking Section -------------------------------
    @osutrack.command(pass_context=True, no_pm=True)
    async def list(self, ctx):
        """Check which players are currently tracked"""
        server = ctx.message.server
        channel = ctx.message.channel
        user = ctx.message.author
        max_users = 30

        em = discord.Embed(colour=user.colour)
        em.set_author(name="osu! Players Currently Tracked in {}".format(server.name), icon_url = server.icon_url)
        channel_users = {}

        target_channel = None
        for track_user in db.track.find({}):
            if "servers" in track_user and server.id in track_user["servers"]:
                target_channel = find(lambda m: m.id == track_user['servers'][server.id]["channel"], server.channels)
                if target_channel.name not in channel_users:
                    channel_users[target_channel.name] = []
                channel_users[target_channel.name].append((track_user['username'], track_user['servers'][server.id]["options"]))

        if target_channel:
            display_num = min(max_users, len(channel_users[target_channel.name]))
        else:
            display_num = 0

        if target_channel:
            channel_users[target_channel.name] = sorted(channel_users[target_channel.name], key=operator.itemgetter(0))
            for channel_name in channel_users.keys():
                display_list = []
                for username, options in channel_users[channel_name][0:display_num]:
                    display_list.append("{} [m:`{}` t:`{}`]".format(username, "|".join(map(str, options['gamemodes'])), str(options['plays'])))

                msg_users = ", ".join(display_list)
                if display_num < len(channel_users[channel_name]):
                    msg_users += "..."
                em.add_field(name = "__#{} ({})__".format(channel_name, len(channel_users[channel_name])), value = msg_users)
        else:
            em.description = "None."
        await self.bot.say(embed = em)

    @osutrack.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def add(self, ctx, *usernames:str):
        """Adds a player to track for top scores.\n"""
        """-m (gamemodes) -t (top # plays)"""
        """osutrack add username1 username2 -m 03 -t 30"""
        server = ctx.message.server
        channel = ctx.message.channel

        key = self.osu_api_key["osu_api_key"]
        msg = ""
        count_add = 0

        if usernames == ():
            await self.bot.say("**Please enter a user (+ Parameters)! e.g. `Stevy -m 02 -t 20`**")
            return

        # gets options for tracking
        options, usernames = await self._get_options(usernames)
        if options == None:
            return

        for username in usernames:
            #try:
            userinfo = list(await get_user(key, self.osu_settings["type"]["default"], username, 0))
            if not userinfo or len(userinfo) == 0:
                msg += "`{}` does not exist in the osu! database.\n".format(username)
            else:
                username = userinfo[0]['username']
                osu_id = userinfo[0]["user_id"]
                track_user = db.track.find_one({"osu_id":osu_id})
                track_user_username = db.track.find_one({"username":username})

                if not track_user:
                    # backwards compatibility
                    if track_user_username and not track_user:
                        print("Existing Create ID")
                        db.track.update_one({"username":username}, {'$set':{"osu_id":osu_id}})
                    else:
                        new_json = {}
                        new_json['username'] = username
                        new_json['osu_id'] = osu_id
                        new_json["servers"] = {}
                        new_json["servers"][server.id] = {}
                        new_json["servers"][server.id]["channel"] = channel.id
                        new_json["servers"][server.id]["options"] = options
                        # add current userinfo
                        new_json["userinfo"] = {}
                        for mode in modes:
                            new_json["userinfo"][mode] = list(await get_user(key, self.osu_settings["type"]["default"], osu_id, self._get_gamemode_number(mode)))[0]

                        # add last tracked time
                        current_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        new_json["last_check"] = current_time
                        db.track.insert_one(new_json)

                    count_add += 1
                    msg += "**`{}` added. Will now track on `#{}`. {}**\n".format(username, channel.name, self._display_options(options))
                else:
                    count_add += 1
                    if "servers" in track_user and server.id in track_user["servers"].keys():
                        track_user["servers"][server.id]["channel"] = channel.id
                        track_user["servers"][server.id]["options"] = options
                        db.track.update_one({"osu_id":osu_id}, {'$set':{
                            "servers.{}.channel".format(server.id):channel.id,
                            "servers.{}.options".format(server.id):options,
                            }})

                        msg += "**Updated tracking `{}` on `#{}`. {}**\n".format(username, channel.name, self._display_options(options))
                    else:
                        db.track.update_one({"osu_id":osu_id}, {'$set':{
                            "servers.{}.channel".format(server.id):channel.id,
                            "servers.{}.options".format(server.id):options,
                            }})
                        msg += "**`{}` now tracking on `#{}`. {}**\n".format(username, channel.name, self._display_options(options))
            #except:
                #pass

        if len(msg) > 500:
            await self.bot.say("**Added `{}` users to tracking on `#{}`. {}**".format(count_add, channel.name,self._display_options(options)))
        else:
            await self.bot.say(msg)

    def _display_options(self, options):
        msg = ""
        gamemodes_str = []
        for mode in options['gamemodes']:
            gamemodes_str.append(str(mode))

        msg += "(Modes: `{}`, Plays: `{}`)".format('|'.join(gamemodes_str), str(options['plays']))
        return msg

    @osutrack.command(pass_context=True, no_pm=True)
    @checks.admin_or_permissions(manage_messages=True)
    async def clear(self, ctx):
        """Clear all tracked users from server."""
        server = ctx.message.server
        user = ctx.message.author

        await self.bot.say('**You are about to clear users tracked on this server. Confirm by typing `yes`.**')
        answer = await self.bot.wait_for_message(timeout=15, author=user)
        if answer is None:
            await self.bot.say('**Clear canceled.**')
        elif "yes" not in answer.content.lower():
            await self.bot.say('**No action taken.**')
        else:
            for username in db.track.find({}):
                servers = username['servers']
                if server.id in servers.keys():
                    del servers[server.id]
                    db.track.update_one({'username':username['username']}, {'$set': {'servers':servers}})
            await self.bot.say('**Users tracked on `{}` cleared.**'.format(server.name))

    async def _get_options(self, usernames:tuple):
        # option parser, these are default
        options = {"gamemodes": [0], "plays": 50}
        if '-m' in usernames:
            marker_loc = usernames.index('-m')
            # check if nothing after
            if len(usernames) - 1 == marker_loc:
                await self.bot.say("**Please provide a mode!**")
                return (None, usernames)

            modes = usernames[marker_loc + 1]
            if not modes.isdigit():
                await self.bot.say("**Please use only whole numbers for number of top plays!**")
                return (None, usernames)

            modes = list(modes)
            valid_modes = [0,1,2,3]
            final_modes = []
            # parse modes into strings
            for mode in modes:
                if int(mode) in valid_modes:
                    final_modes.append(int(mode))

            if not final_modes:
                await self.bot.say("**Please enter valid modes! e.g. `0123`**")
                return (None, usernames)

            final_modes = set(final_modes)
            options["gamemodes"] = sorted(list(final_modes))
            usernames = list(usernames)
            del usernames[marker_loc + 1]
            del usernames[marker_loc]
            usernames = tuple(usernames)

        if '-t' in usernames:
            marker_loc = usernames.index('-t')
            # check if nothing after
            if len(usernames) - 1 == marker_loc:
                await self.bot.say("**Please provide a number for top plays!**")
                return (None, usernames)

            top_num = usernames[marker_loc + 1]
            if top_num.isdigit():
                top_num = int(top_num)
            else:
                await self.bot.say("**Please provide an integer for top plays!**")
                return (None, usernames)

            if top_num > self.osu_settings['num_track'] or top_num < 1:
                await self.bot.say("**Please provide a valid number of plays! (1-{})**".format(self.osu_settings['num_track']))
                return (None, usernames)

            options["plays"] = top_num
            usernames = list(usernames)
            del usernames[marker_loc + 1]
            del usernames[marker_loc]
            usernames = tuple(usernames)
        return (options, usernames)

    @osutrack.command(pass_context=True, no_pm=True)
    @checks.mod_or_permissions(manage_messages=True)
    async def remove(self, ctx, *usernames:str):
        """Removes a player to track for top scores."""
        server = ctx.message.server
        channel = ctx.message.channel
        msg = ""
        count_remove = 0

        if usernames == ():
            await self.bot.say("Please enter a user")
            return

        for username in usernames:
            user_find = db.track.find_one({"username":username})
            if user_find and "servers" in user_find and server.id in user_find["servers"]:
                if channel.id == user_find["servers"][server.id]["channel"]:
                    db.track.update_one({"username":username}, {"$unset":{"servers.{}".format(server.id):"channel"}})
                    msg+="**No longer tracking `{}` in `#{}`.**\n".format(username, channel.name)
                    count_remove += 1
                else:
                    msg+="**`{}` is not currently being tracked in `#{}`.**\n".format(username, channel.name)
            else:
                msg+="**`{}` is not currently being tracked.**\n".format(username)

        if len(msg) > 500:
            await self.bot.say("**Removed `{}` users from tracking on `#{}`.**".format(count_remove, channel.name))
        else:
            await self.bot.say(msg)

    @osutrack.command(pass_context=True, no_pm=True)
    @checks.is_owner()
    async def untrack(self, ctx, *usernames:str):
        """Removes a user from the database."""
        server = ctx.message.server
        channel = ctx.message.channel
        msg = ""
        count_remove = 0

        if answer is None:
            await self.bot.say('**Clear canceled.**')
        elif "yes" not in answer.content.lower():
            await self.bot.say('**No action taken.**')
        else:
            for username in db.track.find({}):
                servers = username['servers']
                if server.id in servers.keys():
                    del servers[server.id]
                    db.track.update_one({'username':username['username']}, {'$set': {'servers':servers}})
            await self.bot.say('**Users tracked on `{}` cleared.**'.format(server.name))

    async def play_tracker(self):
        self._remove_duplicates() # runs on startup

        requests_per_user = 4 # without recent (hardcoded)
        while self == self.bot.get_cog('Osu'):
            print("Time Started.")
            total_tracking = db.track.count() # around 1700 for owo
            total_requests = total_tracking * requests_per_user
            max_cycles_per_min = self.max_requests/requests_per_user
            self.cycle_time = total_tracking/max_cycles_per_min # minutes
            sleep_time = (self.cycle_time * 60) / total_tracking # in seconds

            current_time = datetime.datetime.now()
            loop = asyncio.get_event_loop()
            for player in db.track.find({}, no_cursor_timeout=True):
                loop.create_task(self.player_tracker(player))
                await asyncio.sleep(sleep_time)

            loop_time = datetime.datetime.now()
            elapsed_time = loop_time - current_time
            print("Time ended: " + str(elapsed_time))

            self._remove_bad_servers() # must be separate, otherwise data access error

            if self.cycle_time*60 < 60:
                await asyncio.sleep(60 - self.cycle_time*60)
            else:
                await asyncio.sleep(5) # arbitrarily set

    def _remove_duplicates(self):
        for player in db.track.find({}, no_cursor_timeout=True):
            player_find_count = db.track.find({"username":player['username']}).count()
            if player_find_count == 2:
                db.track.delete_one({"username":player['username']})
                print("Deleted One Instance of {}".format(player['username']))
            elif player_find_count > 2:
                db.track.delete_many({"username":player['username']})
                print("Deleted All Instances of {}".format(player['username']))

    def _remove_bad_servers(self):
        if self.server_send_fail != []:
            for player in db.track.find({}, no_cursor_timeout=True):
                all_servers = player['servers'].keys()
                for failed_server_id in self.server_send_fail:
                    if failed_server_id in all_servers:
                        del player['servers'][failed_server_id]
                        db.track.update_one({"username":player['username']}, {'$set':{"servers":player['servers']}})
                        find_test = db.track.find_one({"username":player['username']})
                        if failed_server_id in find_test['servers'].keys():
                            log.info("FAILED to delete Server {} from {}".format(failed_server_id, player['username']))
                        else:
                            log.info("Deleted Server {} from {}".format(failed_server_id, player['username']))
            self.server_send_fail = []


    # used to track top plays of specified users (someone please make this better c:)
    # Previous failed attempts include exponential blocking, using a single client session (unreliable),
    # threading/request to update info and then displaying separately, aiohttp to update and then displaying separately
    async def player_tracker(self, player):
        key = self.osu_api_key["osu_api_key"]

        # get id, either should be the same, but one is backup
        if 'osu_id' in player:
            osu_id = player['osu_id']
        else:
            osu_id = player['userinfo']['osu']['user_id']

        # create last check just in case it doesn't exist
        if 'last_check' not in player:
            print("Creating Last Check for {}".format(player['username']))
            player['last_check'] = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            db.track.update_one({"username":player['username']}, {'$set':{"last_check":player['last_check']}})

        # ensures that data is recieved
        got_data = False
        get_data_counter = 1
        while(not got_data and get_data_counter <= 10):
            try:
                new_data = await self._fetch_new(osu_id) # contains data for player
                got_data = True
            except:
                print("Data fetch failed for {} ({})".format(player['username'], get_data_counter))
                get_data_counter += 1
            await asyncio.sleep(1)

        # if still no data
        if new_data == None:
            return

        current_time = datetime.datetime.now()

        for mode in modes:
            gamemode_number = self._get_gamemode_number(mode)
            score_gamemode = self._get_gamemode_display(mode)

            best_plays = new_data["best"][mode] # single mode
            recent_play = new_data["recent"][mode] # not used yet

            best_timestamps = []
            for best_play in best_plays:
                best_timestamps.append(best_play['date'])

            top_play_num_tracker = [] # used for pruning
            for i in range(len(best_timestamps)): # max 100
                last_top = player["last_check"]
                last_top_datetime = datetime.datetime.strptime(last_top, '%Y-%m-%d %H:%M:%S')
                best_datetime = datetime.datetime.strptime(best_timestamps[i], '%Y-%m-%d %H:%M:%S')
                if best_datetime > last_top_datetime: # and (current_time.timetuple().tm_yday - best_datetime.timetuple().tm_yday) <= 1: # could just use string...
                    top_play_num = i+1
                    play = best_plays[i]
                    play_map = await get_beatmap(key, self.osu_settings["type"]["default"], play['beatmap_id'])
                    new_user_info = list(await get_user(key, self.osu_settings["type"]["default"], osu_id, gamemode_number))

                    if new_user_info != None and len(new_user_info) > 0 and new_user_info[0]['pp_raw'] != None:
                        new_user_info = new_user_info[0]
                    else:
                        print(player["username"] + "({})".format(osu_id) + " has not played enough.")
                        return

                    # send appropriate message to channel
                    if mode in player["userinfo"]:
                        old_user_info = player["userinfo"][mode]
                        em = self._create_top_play(top_play_num, play, play_map, old_user_info, new_user_info, score_gamemode)
                    else:
                        old_user_info = None
                        em = self._create_top_play(top_play_num, play, play_map, old_user_info, new_user_info, score_gamemode)

                    # display it to the player with info
                    all_servers = player['servers'].keys()
                    for server_id in all_servers:
                        try:
                            server = find(lambda m: m.id == server_id, self.bot.servers)
                            server_settings = db.osu_settings.find_one({"server_id": server_id})
                            if server and (not server_settings or "tracking" not in server_settings or server_settings["tracking"] == True):
                                server_player_info = player['servers'][server_id]
                                if 'options' in server_player_info:
                                    plays_option = server_player_info['options']['plays']
                                    gamemodes_option = server_player_info['options']['gamemodes']
                                if 'options' not in server_player_info or i <= plays_option and  gamemode_number in gamemodes_option:
                                    channel = find(lambda m: m.id == player['servers'][server_id]["channel"], server.channels)
                                    await self.bot.send_message(channel, embed = em)
                        except:
                            log.info("Failed to send to server {}".format(server_id))
                            if server_id not in self.server_send_fail:
                                self.server_send_fail.append(server_id)

                    # calculate latency
                    besttime = datetime.datetime.strptime(best_timestamps[i], '%Y-%m-%d %H:%M:%S')
                    oldlastcheck = datetime.datetime.strptime(last_top, '%Y-%m-%d %H:%M:%S')
                    delta = besttime.minute - oldlastcheck.minute

                    log.info("Created top {} {} play for {}({}) | {} {}".format(top_play_num, mode, new_user_info['username'], osu_id, str(besttime), str(oldlastcheck)))

                    # update userinfo for next use
                    player["last_check"] = best_timestamps[i]
                    # save timestamp for most recent top score
                    if player['username'] != new_user_info['username']:
                        print("Username updated from {} to {}".format(player['username'], new_user_info['username']))
                        db.track.update_one({"username":player['username']}, {'$set':{"username":new_user_info['username']}})
                        player['username'] = new_user_info['username']
                    db.track.update_one({"username":player['username']}, {'$set':{"userinfo.{}".format(mode):new_user_info}})
                    db.track.update_one({"username":player['username']}, {'$set':{"last_check":best_timestamps[i]}})

                    # if player['username'] in ['Dahcreeper','Mking', 'Badewanne3', 'Nainor', 'ItsWinter','kablaze', 'Asu Nya', 'AlexDark69','dinnozap']:
                    # player_find_count = db.track.find({"username":player['username']}).count()
                    # print("Found {} entries for {}.".format(str(player_find_count), player['username']))
                    # log.info(str(player_find))

        #except:
            # log.info("Failed to load top scores for {}".format(player['username']))
            #pass

    async def _fetch_new(self, osu_id):
        key = self.osu_api_key["osu_api_key"]
        new_data = {"best":{}, "recent":{}}

        try:
            for mode in modes:
                new_data["best"][mode] = await get_user_best(
                    key, self.osu_settings["type"]["default"], osu_id,
                    self._get_gamemode_number(mode), self.osu_settings["num_track"])
                """new_data["recent"][mode] = await get_user_recent(
                    key, self.osu_settings["type"]["default"], osu_id,
                    self._get_gamemode_number(mode))"""
                new_data["recent"][mode] = {}
            return new_data
        except:
            return None

    def _create_top_play(self, top_play_num, play, beatmap, old_user_info, new_user_info, gamemode):
        beatmap_url = 'https://osu.ppy.sh/b/{}'.format(play['beatmap_id'])
        user_url = 'https://{}/u/{}'.format(self.osu_settings["type"]["default"], new_user_info['user_id'])
        profile_url = 'http://s.ppy.sh/a/{}.png'.format(new_user_info['user_id'])
        beatmap = beatmap[0]

        # get infomation
        m0, s0 = divmod(int(beatmap['total_length']), 60)
        mods = self.num_to_mod(play['enabled_mods'])
        em = discord.Embed(description='', colour=0xffa500)
        acc = self.calculate_acc(play, int(beatmap['mode']))

        # determine mods
        if not mods:
            mods = []
            mods.append('No Mod')
            oppai_output = None
        else:
            oppai_mods = "+{}".format("".join(mods))
            oppai_output = get_pyoppai(beatmap['beatmap_id'], accs=[int(acc)], mods = int(play['enabled_mods']))

        # grab beatmap image
        page = urllib.request.urlopen(beatmap_url)
        soup = BeautifulSoup(page.read(), "html.parser")
        map_image = [x['src'] for x in soup.findAll('img', {'class': 'bmt'})]
        map_image_url = 'http:{}'.format(map_image[0])
        em.set_thumbnail(url=map_image_url)
        em.set_author(name="New #{} for {} in {}".format(top_play_num, new_user_info['username'], gamemode), icon_url = profile_url, url = user_url)

        info = ""
        info += "▸ [**__{} [{}]__**]({})                    \n".format(beatmap['title'], beatmap['version'], beatmap_url)
        # calculate bpm and time... MUST clean up.
        if oppai_output and ('DT' in str(mods).upper() or 'HT' in str(mods).upper()):
            if 'DT' in str(mods):
                m1,s1,bpm1 = self._calc_time(beatmap['total_length'], beatmap['bpm'], 1.5)
            elif 'HT' in str(mods):
                m1,s1,bpm1 = self._calc_time(beatmap['total_length'], beatmap['bpm'], 2/3)
            info += "▸ **{}★** ▸ {}:{}({}:{}) ▸ {}({})bpm\n".format(
                self._compare_val(beatmap['difficultyrating'], oppai_output, 'stars', dec_places = 2),
                m0, str(s0).zfill(2),
                m1, str(s1).zfill(2),
                beatmap['bpm'], bpm1)
        elif 'DT' in str(mods).upper() or 'HT' in str(mods).upper():
            if 'DT' in str(mods):
                m1,s1,bpm1 = self._calc_time(beatmap['total_length'], beatmap['bpm'], 1.5)
            elif 'HT' in str(mods):
                m1,s1,bpm1 = self._calc_time(beatmap['total_length'], beatmap['bpm'], 2/3)
            info += "▸ **{}★** ▸ {}:{}({}:{}) ▸ {}({})bpm\n".format(
                self._compare_val(beatmap['difficultyrating'], oppai_output, 'stars', dec_places = 2),
                m0, str(s0).zfill(2),
                m1, str(s1).zfill(2),
                beatmap['bpm'], bpm1)
        else:
            info += "▸ **{}★** ▸ {}:{} ▸ {}bpm\n".format(
                self._compare_val(beatmap['difficultyrating'], oppai_output, 'stars', dec_places = 2),
                m0, str(s0).zfill(2), beatmap['bpm'])
        if old_user_info != None:
            dpp = float(new_user_info['pp_raw']) - float(old_user_info['pp_raw'])
            if dpp == 0:
                pp_gain = ""
            else:
                pp_gain = "({:+.2f})".format(dpp)
            info += "▸ +{} ▸ **{:.2f}%** ▸ **{}** Rank ▸ **{:.2f} {}pp**\n".format(self._fix_mods(''.join(mods)),
                float(acc), play['rank'], float(play['pp']), pp_gain)
            info += "▸ {} ▸ x{}/{} ▸ [{}/{}/{}/{}]\n".format(
                play['score'], play['maxcombo'], beatmap['max_combo'],
                play['count300'],play['count100'],play['count50'],play['countmiss'])
            info += "▸ #{} → #{} ({}#{} → #{})".format(
                old_user_info['pp_rank'], new_user_info['pp_rank'],
                new_user_info['country'],
                old_user_info['pp_country_rank'], new_user_info['pp_country_rank'])
        else: # if first time playing
            info += "▸ +{} ▸ **{:.2f}%** ▸ **{}** Rank ▸ **{:.2f}pp**\n".format(
                self._fix_mods(''.join(mods)), float(acc), play['rank'], float(play['pp']))
            info += "▸ {} ▸ x{}/{} ▸ [{}/{}/{}/{}]\n".format(
                play['score'], play['maxcombo'], beatmap['max_combo'],
                play['count300'],play['count100'],play['count50'],play['countmiss'])
            info += "▸ #{} ({}#{})".format(
                new_user_info['pp_rank'],
                new_user_info['country'],
                new_user_info['pp_country_rank'])
        em.description = info

        time_ago = self._time_ago(
            datetime.datetime.utcnow() + datetime.timedelta(hours=8),
            datetime.datetime.strptime(play['date'], '%Y-%m-%d %H:%M:%S'))
        print(time_ago)
        em.set_footer(text = "{}Ago On osu! Official Server".format(time_ago))
        return em

###-------------------------Python wrapper for osu! api-------------------------

# Gets the beatmap
async def get_beatmap(key, api:str, beatmap_id, session = None):
    url_params = []
    url_params.append(parameterize_key(key))
    url_params.append(parameterize_id("b", beatmap_id))
    url = build_request(url_params, "https://{}/api/get_beatmaps?".format(api))
    return await fetch(url, session)

# Gets the beatmap set
async def get_beatmapset(key, api:str, set_id, session = None):
    url_params = []

    url_params.append(parameterize_key(key))
    url_params.append(parameterize_id("s", set_id))
    url = build_request(url_params, "https://{}/api/get_beatmaps?".format(api))
    return await fetch(url, session)

# Grabs the scores
async def get_scores(key, api:str, beatmap_id, user_id, mode, session = None):
    url_params = []
    url_params.append(parameterize_key(key))
    url_params.append(parameterize_id("b", beatmap_id))
    url_params.append(parameterize_id("u", user_id))
    url_params.append(parameterize_mode(mode))
    url = build_request(url_params, "https://{}/api/get_scores?".format(api))
    return await fetch(url, session)

async def get_user(key, api:str, user_id, mode, session = None):
    url_params = []
    url_params.append(parameterize_key(key))
    url_params.append(parameterize_id("u", user_id))
    url_params.append(parameterize_mode(mode))
    url = build_request(url_params, "https://{}/api/get_user?".format(api))
    return await fetch(url, session)

async def get_user_best(key, api:str, user_id, mode, limit, session = None):
    url_params = []
    url_params.append(parameterize_key(key))
    url_params.append(parameterize_id("u", user_id))
    url_params.append(parameterize_mode(mode))
    url_params.append(parameterize_limit(limit))

    async with aiohttp.get(build_request(url_params, "https://{}/api/get_user_best?".format(api))) as resp:
        return await resp.json()

# Returns the user's ten most recent plays.
async def get_user_recent(key, api:str, user_id, mode, session = None):
    url_params = []

    url_params.append(parameterize_key(key))
    url_params.append(parameterize_id("u", user_id))
    url_params.append(parameterize_mode(mode))
    url = build_request(url_params, "https://{}/api/get_user_recent?".format(api))
    return await fetch(url, session)

async def fetch(url, session):
    if session == None:
        async with aiohttp.get(url) as resp:
            return await resp.json()
    else:
        async with session.get(url) as resp:
            return await resp.json()

# Written by Jams
def get_pyoppai(map_id:str, accs=[100], mods=0, misses=0, combo=None, completion=None, fc=None):
    url = 'https://osu.ppy.sh/osu/{}'.format(map_id)

    try:
        ctx = pyoppai.new_ctx()
        b = pyoppai.new_beatmap(ctx)

        BUFSIZE = 2000000
        buf = pyoppai.new_buffer(BUFSIZE)

        btmap = wget.download(url)
        pyoppai.parse(btmap, b, buf, BUFSIZE, False, btmap)
        dctx = pyoppai.new_d_calc_ctx(ctx)
        pyoppai.apply_mods(b, mods)

        stars, aim, speed, _, _, _, _ = pyoppai.d_calc(dctx, b)
        cs, od, ar, hp = pyoppai.stats(b)

        if not combo:
            combo = pyoppai.max_combo(b)

        total_pp_list = []
        aim_pp_list = []
        speed_pp_list = []
        acc_pp_list = []

        for acc in accs:
            accurracy, pp, aim_pp, speed_pp, acc_pp = pyoppai.pp_calc_acc(ctx, aim, speed, b, acc, mods, combo, misses)
            total_pp_list.append(pp)
            aim_pp_list.append(aim_pp)
            speed_pp_list.append(speed_pp)
            acc_pp_list.append(acc_pp)

        if fc:
            _, fc_pp, _, _, _ = pyoppai.pp_calc_acc(ctx, aim, speed, b, fc, mods, pyoppai.max_combo(b), 0)
            total_pp_list.append(fc_pp)

        pyoppai_json = {
            'version': pyoppai.version(b),
            'title': pyoppai.title(b),
            'artist': pyoppai.artist(b),
            'creator': pyoppai.creator(b),
            'combo': combo,
            'misses': misses,
            'max_combo': pyoppai.max_combo(b),
            'mode': pyoppai.mode(b),
            'num_objects': pyoppai.num_objects(b),
            'num_circles': pyoppai.num_circles(b),
            'num_sliders': pyoppai.num_sliders(b),
            'num_spinners': pyoppai.num_spinners(b),
            'stars': stars,
            'aim_stars': aim,
            'speed_stars': speed,
            'pp': total_pp_list, # list
            'aim_pp': aim_pp_list,
            'speed_pp': speed_pp_list,
            'acc_pp': acc_pp_list,
            'acc': accs, # list
            'cs': cs,
            'od': od,
            'ar': ar,
            'hp': hp
            }

        if completion:
            try:
                pyoppai_json['map_completion'] = _map_completion(btmap, int(completion))
            except:
                pass

        os.remove(btmap)
        return pyoppai_json
    except:
        return None

# Written by Jams
def get_pyoppai_multi(url:str):
    ctx = pyoppai.new_ctx()
    b = pyoppai.new_beatmap(ctx)
    BUFSIZE = 2000000
    buf = pyoppai.new_buffer(BUFSIZE)
    btmap = wget.download(url)
    pyoppai.parse(btmap, b, buf, BUFSIZE, False, btmap)
    dctx = pyoppai.new_d_calc_ctx(ctx)
    stars, aim, speed, rhythm_awkwardness, naim_singles, ntiming_singles, nthreshold_singles = pyoppai.d_calc(dctx, b)
    cs, od, ar, hp = pyoppai.stats(b)
    combo = pyoppai.max_combo(b)
    nomod = 0

    # define all mods
    hd = pyoppai.hd
    hdhr = pyoppai.hd | pyoppai.hr
    dt = pyoppai.dt
    dthd = pyoppai.dt | pyoppai.hd
    dthdhr = pyoppai.dt | pyoppai.hd | pyoppai.hr
    fl = pyoppai.fl
    hdfl = pyoppai.hd | pyoppai.fl
    hdhrfl = pyoppai.hd | pyoppai.hr | pyoppai.fl
    dtfl = pyoppai.dt | pyoppai.fl
    dthdfl = pyoppai.dt | pyoppai.hd | pyoppai.fl
    dthdhrfl = pyoppai.dt | pyoppai.hd | pyoppai.hr | pyoppai.fl

    # list of all mods
    mods = [nomod, hd, hdhr, dt, dthd, dthdhr, fl, hdfl, hdhrfl, dtfl, dthdfl, dthdhrfl]

    pp_list = []
    for mod in mods:
        pyoppai.apply_mods(b, mod)
        acc, pp, aim_pp, speed_pp, acc_pp = pyoppai.pp_calc_acc(ctx, aim, speed, b, acc, mod, combo, 0)
        pp_list.append(pp)
    return pp_list

def _map_completion(btmap, totalhits=0):
    btmap = open(btmap, 'r').read()
    btmap = Beatmap(btmap)
    good = btmap.parse()
    if not good:
        raise ValueError("Beatmap verify failed. "
                         "Either beatmap is not for osu! standart, or it's malformed")
        return
    hitobj = []
    if totalhits == 0:
        totalhits = len(btmap.hit_objects)
    numobj = totalhits - 1
    num = len(btmap.hit_objects)
    for objects in btmap.hit_objects:
        hitobj.append(objects.time)
    timing = int(hitobj[num - 1]) - int(hitobj[0])
    point = int(hitobj[numobj]) - int(hitobj[0])
    map_completion = (point / timing) * 100
    return map_completion

# Returns the full API request URL using the provided base URL and parameters.
def build_request(url_params, url):
    for param in url_params:
        url += str(param)
        if (param != ""):
            url += "&"
    return url[:-1]

def parameterize_event_days(event_days):
    if (event_days == ""):
        event_days = "event_days=1"
    elif (int(event_days) >= 1 and int(event_days) <= 31):
        event_days = "event_days=" + str(event_days)
    else:
        print("Invalid Event Days")
    return event_days

def parameterize_id(t, id):
    if (t != "b" and t != "s" and t != "u" and t != "mp"):
        print("Invalid Type")
    if (len(str(id)) != 0):
        return t + "=" + str(id)
    else:
        return ""

def parameterize_key(key):
    if (len(key) == 40):
        return "k=" + key
    else:
        print("Invalid Key")

def parameterize_limit(limit):
    ## Default case: 10 scores
    if (limit == ""):
        limit = "limit=10"
    elif (int(limit) >= 1 and int(limit) <= 100):
        limit = "limit=" + str(limit)
    else:
        print("Invalid Limit")
    return limit

def parameterize_mode(mode):
    ## Default case: 0 (osu!)
    if (mode == ""):
        mode = "m=0"
    elif (int(mode) >= 0 and int(mode) <= 3):
        mode = "m=" + str(mode)
    else:
        print("Invalid Mode")
    return mode

###-------------------------Setup-------------------------
def check_folders():
    if not os.path.exists("data/osu"):
        print("Creating data/osu folder...")
        os.makedirs("data/osu")

def check_files():
    osu_api_key = {"osu_api_key" : ""}
    api_file = "data/osu/apikey.json"

    if not fileIO(api_file, "check"):
        print("Adding data/osu/apikey.json...")
        fileIO(api_file, "save", osu_api_key)
    else:  # consistency check
        current = fileIO(api_file, "load")
        if current.keys() != osu_api_key.keys():
            for key in system.keys():
                if key not in osu_api_key.keys():
                    current[key] = osu_api_key[key]
                    print("Adding " + str(key) +
                          " field to osu apikey.json")
            fileIO(api_file, "save", current)

    # creates file for server to use
    settings_file = "data/osu/osu_settings.json"
    if not fileIO(settings_file, "check"):
        print("Adding data/osu/osu_settings.json...")
        fileIO(settings_file, "save", {
            "type": {
                "default": "osu.ppy.sh",
                "ripple":"ripple.moe"
                },
            "num_track" : 50,
            "num_best_plays": 5,
            })

def setup(bot):
    check_folders()
    check_files()

    n = Osu(bot)
    loop = asyncio.get_event_loop()
    loop.create_task(n.play_tracker())
    bot.add_listener(n.find_link, "on_message")
    bot.add_cog(n)