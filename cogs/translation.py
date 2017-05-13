import os
from translation import baidu, google, youdao, iciba
from translation import (set_default_translation, set_default_language,
    set_default_proxies, get, ConnectError)
from .utils import checks
from discord.ext import commands
from .utils.dataIO import fileIO

class Translate:
    def __init__(self, bot):
        self.bot = bot

    @commands.command(pass_context=True, name='translate', aliases=['tr'])
    async def translate(self, ctx, source:str, dest:str, *text:str):
        """
            Translate text to another language.
        """
        user = ctx.message.author

        if text == "" or text == None:
            await self.bot.say("Please enter some text!")
            return

        try:
            set_default_translation('baidu')
            set_default_language(source, dest)
            translated_text = get(text)
            await self.bot.say('**{} ({})**: `{}`'.format(user.mention, dest, translated_text))
        except:
            await self.bot.say("Not a a destination language! Please do `>languages`")

    @commands.command(pass_context=True, name='languages', aliases=['lang'])
    async def languages(self, ctx):
        """
            List Languages
        """
        user = ctx.message.author
        languages = {'el'   : 'Greek',
            'en'    : 'English',
            'est'   : 'Estonian',
            'it'    : 'Italian',
            'swe'    : 'Swedish',
            'cs'    : 'Czech',
            'ara'    : 'Arabic',
            'spa'    : 'Spanish',
            'ru'    : 'Russian',
            'nl'    : 'Dutch',
            'pt'    : 'Portuguese',
            'th'    : 'Thai',
            'vie'    : 'Vietnamese',
            'rom'    : 'Romanian',
            'pl'    : 'Polish',
            'fra'    : 'French',
            'bul'    : 'Bulgarian',
            'slo'    : 'Slovenian',
            'da'    : 'Danish',
            'hu'    : 'Hungarian',
            'jp'    : 'Japanese',
            'ka'    : 'Georgian',
            'zh'    : 'Chinese',
            'wyw'   : 'Chinese (Traditional)',
            'yue'   : 'Contonese',
            'kor'    : 'Korean',
            'de'    : 'German',
            'fin'   : 'Finnish',
            }

        ret_list = []
        for abbr in sorted(languages.keys()):
            ret_list.append("{}(`{}`)".format(languages[abbr], abbr))

        msg = ", ".join(ret_list)
        await self.bot.say("**List of available languages: **\n\n{}".format(msg))


def setup(bot):
    n = Translate(bot)
    bot.add_cog(n)