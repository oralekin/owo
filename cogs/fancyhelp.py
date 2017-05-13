import discord
import os
import collections
from .utils.dataIO import fileIO, dataIO
from .utils import checks
from discord.ext import commands

class Help:
    def __init__(self, bot):
        self.bot = bot
        self.profile = "data/help/toggle.json"
        self.settings = dataIO.load_json(self.profile)

    @commands.command(pass_context=True, hidden = True)
    @checks.is_owner()
    async def sethelp(self, ctx):
        self.profile = "data/help/toggle.json"
        self.settings = dataIO.load_json(self.profile)
        dm_msg = "The help message will now be send in DM."
        no_dm_msg = "The help message will now be send into the channel."
        if 'toggle' not in self.settings:
            self.settings['toggle'] = "no_dm"
            dataIO.save_json(self.profile, self.settings)
            msg = no_dm_msg
        elif self.settings['toggle'] == "dm":
            self.settings['toggle'] = "no_dm"
            dataIO.save_json(self.profile, self.settings)
            msg = no_dm_msg
        elif self.settings['toggle'] == "no_dm":
            self.settings['toggle'] = "dm"
            dataIO.save_json(self.profile, self.settings)
            msg = dm_msg
        if msg:
            await self.bot.say(msg)

    @commands.command(name='help', pass_context=True, hidden = True)
    async def _help(self, ctx, command = None):
        user = ctx.message.author
        server = ctx.message.server

        if 'toggle' not in self.settings:
            self.settings['toggle'] = "dm"
            dataIO.save_json(self.profile, self.settings)
            await self.bot.say("Help message is set to DM by default. use "
                               "**{}sethelp** to change it!".format(ctx.prefix))
            toggle = self.settings['toggle']
        else:
            toggle = self.settings['toggle']
        if not command:
            msg = "Command list for {}:".format(self.bot.user.name)
            color = 0xffa500

            em=discord.Embed(description='', color=color)
            em.set_author(name=msg, icon_url = self.bot.user.avatar_url, url = 'https://discord.gg/aNKde73')

            final_coms = {}
            com_groups = []
            for com in self.bot.commands:
                try:
                    if self.bot.commands[com].module.__name__ not in com_groups:
                        com_groups.append(self.bot.commands[com].module.__name__)
                    else:
                        continue
                except Exception as e:
                        print(e)
                        print(datetime.datetime.now())
                        continue
            com_groups.sort()
            alias = []
            # sorting command into the correct cog
            for com_group in com_groups:
                commands = []
                for com in self.bot.commands:
                    if com in self.bot.commands[com].aliases:
                        continue
                    if com_group == self.bot.commands[com].module.__name__:
                        commands.append(com)
                final_coms[com_group] = commands

            final_coms = collections.OrderedDict(sorted(final_coms.items()))
            desc = ''
            ignore_groups = ['Random', 'Downloader', 'Fancyhelp', 'Owner', 'Random', 'Cleverbot', 'Welcome', 'Wolfram']
            for group in final_coms:
                cog_name = group.replace("cogs.", "").title()
                if cog_name not in ignore_groups:
                    desc += '**{}** - '.format(cog_name)
                    final_coms[group].sort()
                    count = 0
                    for com in final_coms[group]:
                        if count == 0:
                            desc += '`{}`'.format(com)
                        else:
                            desc += ' `{}`'.format(com)
                        count += 1
                    desc += "\n"

            em.description = desc
            em.set_footer(text = "Join the owo! Official server: https://discord.gg/aNKde73")

            if toggle == "dm":
                await self.bot.say("Hey there, {}! I sent you a list of commands"
                                   " through DM.".format(ctx.message.author.mention))
                await self.bot.send_message(ctx.message.author, embed=em)
            elif toggle == 'no_dm':
                await self.bot.say(embed=em)

        else:
            msg = "'{}' Command Usage".format(self.bot.user.name)
            color = 0xffa500

            try:
                text = command
                info = self.bot.commands[command].help
                em=discord.Embed(description=info, color=color)
                em.set_author(name=text, icon_url = self.bot.user.avatar_url)
                await self.bot.say(embed=em)
            except Exception as e:
                print(e)
                await self.bot.say("Couldn't find command! Try again.")

def check_folder():
    if not os.path.exists("data/help"):
        print("Creating data/help folder")
        os.makedirs("data/help")

def check_file():
    data = {}
    f = "data/help/toggle.json"
    if not dataIO.is_valid_json(f):
        print("Creating data/help/toggle.json")
        dataIO.save_json(f, data)

def setup(bot):
    check_folder()
    check_file()
    bot.remove_command('help')
    bot.add_cog(Help(bot))