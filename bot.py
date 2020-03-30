#!/usr/bin/python
# -*- coding: utf-8 -*-

import fnmatch
import os
import random
import sched

import discord
import pytesseract
from PIL import Image, ImageFilter, ImageEnhance, ImageOps
from discord.ext import commands
from fuzzywuzzy import process
from tinydb import TinyDB, Query

bot = commands.Bot(command_prefix="!")
bot.needs_quote_nums_update = True
bot.cached_quote_nums = []

bot.db = TinyDB("./quote_bot.json")
bot.quote_search = bot.db.table("search")

image_exts = ["png", "jpg", "jpeg", "gif"]
other_exts = ["mp4", "mp3", "wav"]


def get_quote_nums():
    if not bot.needs_quote_nums_update:
        return bot.cached_quote_nums
    quote_files = next(os.walk("quotes/"))[2]
    quote_file_nums = [int(x.rsplit(".", 1)[0]) for x in quote_files]
    quote_file_exts = [x.rsplit(".", 1)[1] for x in quote_files]
    for i in range(len(quote_file_nums)):
        ocrQuote(quote_file_nums[i], quote_file_exts[i])
    quote_file_nums.sort()
    bot.needs_quote_nums_update = False
    bot.cached_quote_nums = quote_file_nums
    return quote_file_nums


def ocrQuote(quote_num, ext):
    if ext not in image_exts or ext == "gif":
        return
    quote_query = Query()
    if len(bot.quote_search.search(quote_query.quote == quote_num)) > 0:
        return
    im = Image.open("quotes/{0}.{1}".format(quote_num, ext))
    im = im.convert("RGB")
    newpixels = []
    pixels = im.getdata()
    num_pixels = len(pixels)
    dark_pixels = 0
    for pixel in pixels:
        if pixel[0] < 90 and pixel[1] < 90 and pixel[2] < 90:
            dark_pixels += 1
    if dark_pixels / num_pixels > 0.7:
        for pixel in pixels:
            if pixel[0] < 90 and pixel[1] < 90 and pixel[2] < 90:
                newpixels.append((255, 255, 255))
            else:
                newpixels.append((0, 0, 0))
    im = im.filter(ImageFilter.UnsharpMask())
    im.putdata(newpixels)
    temp_string = "temp{0}.jpg".format(quote_num)
    im.save(temp_string)
    string = pytesseract.image_to_string(Image.open(temp_string), lang="eng",
                                         nice=-3)
    os.remove(temp_string)
    print("Quote {0}:\n===================\n{1}\n===================\n".format(quote_num, string))
    bot.quote_search.upsert({"quote": quote_num, "string": string, "ext": ext}, quote_query.quote == quote_num)


bot.current_quote = max(get_quote_nums())
print(bot.current_quote.__str__())


def find(pattern, path):
    for root, dirs, files in os.walk(path):
        for name in files:
            if fnmatch.fnmatch(name, pattern):
                return os.path.join(root, name)


@bot.command(name="quote", help="get a specific or random quote")
async def quote(ctx, *args):
    if ctx.author.bot:
        return
    quote_num = -1
    specified_id = False
    valid_id = True
    pending_num = -1
    if len(args) > 0 and args[0]:
        arg1 = args[0]
        try:
            pending_num = int(arg1)
            specified_id = True
            if 0 < pending_num <= ctx.bot.current_quote:
                quote_num = pending_num
        except ValueError:
            pass
    if quote_num is -1:
        valid_id = False
        quote_num = random.choice(get_quote_nums())
    file_name = find("{0}.*".format(quote_num), "quotes/")
    if file_name is None or len(file_name) < 1:
        valid_id = False
        quote_num = random.choice(get_quote_nums())
        file_name = find("{0}.*".format(quote_num), "quotes/")
    if file_name:
        discord_file = discord.File(file_name)
        if specified_id and not valid_id:
            await ctx.send("Random quote {0} (specified quote {1} was not found)".format(quote_num, pending_num),
                           file=discord_file)
        elif specified_id:
            try:
                await ctx.send("Quote {0}".format(pending_num), file=discord_file)
            except Exception as e:
                print(e)
                await ctx.send("Sending quote {0} failed.".format(pending_num))
        else:
            try:
                await ctx.send("Random quote {0}".format(quote_num), file=discord_file)
            except Exception as e:
                print(e)
                await ctx.send("Sending quote {0} failed.".format(pending_num))
    else:
        await ctx.send("Quote not found.")


@bot.command(name="searchquotes", help="search through all quotes")
async def searchquotes(ctx, *, arg):
    quotes = [d["string"] for d in ctx.bot.quote_search.all()]
    found_quotes_strings = process.extractBests(arg, quotes, score_cutoff=0.5, limit=10)
    found_quotes_strings = [x[0] for x in found_quotes_strings]
    quote_query = Query()
    found_quotes = []
    for quote_string in found_quotes_strings:
        found_quotes.extend(ctx.bot.quote_search.search(quote_query.string == quote_string))
    if len(found_quotes) > 0:
        quote_list = "{0} (attached)".format(found_quotes[0]["quote"])
        files = [discord.File("quotes/{0}.{1}".format(found_quotes[0]["quote"],
                                                      found_quotes[0]["ext"]))]
        if len(found_quotes) > 1:
            for quote_doc in range(1, len(found_quotes)):
                quote_list += ", {0}".format(found_quotes[quote_doc]["quote"])
                files.append(discord.File("quotes/{0}.{1}".format(found_quotes[quote_doc]["quote"],
                                                                  found_quotes[quote_doc]["ext"])))
        if len(found_quotes) > 1:
            await ctx.send("Found {0} quotes for search query \"{1}\": {2}.".format(len(found_quotes), arg, quote_list),
                           file=files[0])
        else:
            await ctx.send("Found 1 quote for search query \"{0}\": {1}.".format(arg, quote_list), files=files)
    else:
        await ctx.send("Could not find any quotes for search query \"{0}\".".format(arg))


@bot.command(name="addquote", help="add a quote by attaching an image through Discord")
async def addquote(ctx):
    if len(ctx.message.attachments) > 0:
        attachment = ctx.message.attachments[0]
        ext = attachment.filename.rsplit(".", 1)[1]
        ext = ext.lower()
        if ext in image_exts and attachment.height > 0 and attachment.width > 0 or ext in other_exts:
            if attachment.size > 8388119:
                await ctx.send("Your quote must be less than ~8MB (8388120 bytes)!")
                return
            try:
                pending_quote = ctx.bot.current_quote + 1
                await attachment.save("quotes/{0}.{1}".format(pending_quote, ext))
                ctx.bot.current_quote = pending_quote
                bot.needs_quote_nums_update = True
                ocrQuote(pending_quote, ext)
                await ctx.send("Added as quote {0}.".format(ctx.bot.current_quote))
            except Exception as e:
                print(e)
                await ctx.send("Saving quote failed. Please try again later.")
            return
    await ctx.send("Please attach an image directly using Discord to add a quote!")


@bot.command(name="listquotes", help="get a direct message of a list of all valid quote numbers")
async def listquotes(ctx):
    quote_nums = [x.__str__() for x in get_quote_nums()]
    await ctx.author.send("Available quotes: {0}".format(", ".join(quote_nums)))


bot.run(os.environ['QUOTE_TOKEN'])
