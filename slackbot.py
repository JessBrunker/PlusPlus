#!/usr/bin/python3

import os
import time
import re
import sqlite3

from slackclient import SlackClient
from slack_code import code as sc


# instantiate Slack client
slack_client = SlackClient(sc)

# bot's user ID in Slack: value assigned after startup
bot_id = None
# dict for user_id: username pairs
user_ids = {}

# constants
RTM_READ_DELAY = 1 # 1 second delay between reading from RTM
# Finds bot commands e.g. @bot help
BOT_MENTION_REGEX = '^<@{}>\s([A-Za-z0-9\s]+)\s?(\S+)?$'
USER_PP_REGEX = '<@(|[WU].+?)>\s?([+-]){2}' # finds @user++
OTHER_PP_REGEX = '@\s?([-_A-Za-z0-9:#]+[^>])\s?([+-]){2}' # finds @anything++
DB_FILE = 'scores.db'


def parse_messages(slack_events):
    '''
    Parse incoming messages looking for instances of ++ or --. Returns two
    lists, one for users and one for everything else, all of which are getting
    a plusplus, and the channel the post occurred in. Excludes the poster from
    giving a plusplus to themselves and shames them.
    '''
    for event in slack_events:
        if event['type'] == 'message' and not 'subtype' in event:
            # check for '@bot {command}
            command_matches = re.search(BOT_MENTION_REGEX, event['text'])
            if command_matches and command_matches.group(1):
                bot_command = command_matches.group(1)
                parameters = command_matches.group(2)
                handle_command(bot_command, parameters, event['channel'])
                return None, None, None # do not allow ++ in a bot command

            # check for @user++
            pp_mentions = re.findall(USER_PP_REGEX, event['text'])
            # don't want users to ++/-- themselves
            # we must shame them
            if self_gratification(event['user'], pp_mentions):
                post_message('<@{}> just pat yourself on the back'.format(
                    event['user']), event['channel'])
            # list all mentions not including the poster
            pp_mentions = set(filter(
                lambda x: x[0] != event['user'], pp_mentions))

            # check for @nonuser++
            pp_others = re.findall(OTHER_PP_REGEX, event['text'])
            # want to exclude any entries that are actually usernames
            pp_others = set(filter(
                lambda x: x not in pp_mentions, pp_others))

            return pp_mentions, pp_others, event['channel']
    return None, None, None


def self_gratification(user, mentions):
    '''
    Returns True if the user is trying to give themselves a plusplus
    '''
    for mention in mentions:
        if user == mention[0]:
            return True
    return False


def handle_plusplus_mentions(mentions, channel):
    '''
    Increment a user's point value if the symbol is a '+', and decrement
    the user's point value if the symbol is a '-' and update the values in
    the database. Print out the user's total after the operation is complete.
    '''
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for mention in mentions:
        user_id, symbol = mention
        user = (user_id,) # used to prevent SQL injections
        c.execute('''SELECT User, Score FROM UserScores
                    WHERE User = ?''', user)
        user_values = c.fetchone()
    
        if not user_values: # user isn't in table yet
            init_points = 1 if symbol == '+' else -1
            user_values = (user_id, init_points)
            c.execute('INSERT INTO UserScores VALUES (?, ?)', user_values)
        else:
            score = user_values[1]
            if symbol == '+':
                score += 1
            else:
                score -= 1
            user_values = (user_id, score)
            # need to reverse the tuple to fit the query
            c.execute('''UPDATE UserScores SET Score = ?
                    WHERE User = ?''', (user_values[1], user_values[0]))
        post_message('<@{}> total points: {}'.format(
            user_values[0], user_values[1]), channel)
    conn.commit()


def handle_plusplus_others(pp_instances, channel):
    '''
    Increment the point value for arbitrary text if the symbol is a '+', and 
    decrement the text's point value if the symbol is a '-' and update the
    values in the database. Print out the text's total after the operation
    is complete.
    '''
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for instance in pp_instances:
        name, symbol = instance
        name = name.strip()
        name_tup = (name,) # prevent SQL injections
        c.execute('''SELECT Name, Score FROM OtherScores
            WHERE Name = ?''', name_tup)
        name_values = c.fetchone()

        if not name_values: # name isn't in table yet
            init_points = 1 if symbol == '+' else -1
            name_values = (name, init_points)
            c.execute('INSERT INTO OtherScores VALUES (?, ?)', name_values)
        else:
            score = name_values[1]
            if symbol == '+':
                score += 1
            else:
                score -= 1
            name_values = (name, score)
            # need to reverse the tuple to fit the query
            c.execute('''UPDATE OtherScores SET Score = ?
                WHERE Name = ?''', (name_values[1], name_values[0]))
        post_message('@{} total points: {}'.format(
            name_values[0], name_values[1]), channel) 
    conn.commit()


def handle_command(cmd, params, channel):
    '''
    Given a bot command, call the appropriate function to manage the command.
    Use the output to create a message to be posted to the channel.
    '''
    # split '@bot do some things' into [do] [some things]
    command = cmd.lower().strip()
    if params:
        params = params.split()
    message = ''

    # Show the top 5 scores in both tables
    if command in ['leaderboard', 'top']:
        message = handle_lookup_users(5)
        message += '\n\n'
        message += handle_lookup_others(5)
    # Show the score for a given user or other object
    elif command == 'lookup':
        if params:
            subject = params[0]
            result = handle_lookup_one(subject)
            message = '{} has {} point'.format(subject,result)
        else:
            message = 'I don\'t know who you want me to lookup. " \
            "Type "<@{0}> lookup @user" or "<@{0}> lookup @text"'.format(bot_id)
    # Show the bottom 5 scores in both tables
    elif command == 'bottom':
        message = handle_lookup_users(-5)
        message += '\n\n'
        message += handle_lookup_others(-5)
    # Show the help message
    elif command in ['help', 'usage', 'commands', 'options']:
        print_help(channel)
        return
    # Unknown command
    else:
        message = "I don't know what you want me to do. " \
                  "Try typing <@{}> help".format(bot_id)
    post_message(message, channel)


def handle_lookup_users(amount):
    '''
    Find a given amount of users from the UserScores table. If amount < 0, we
    need to find the lowest scores. Returns a string with the formatted data.
    '''
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    query = 'SELECT * FROM UserScores ORDER BY Score'
    # We need the top 5 scores
    if amount > 0:
        query += ' DESC'
    message = '*Users leaderboard*'
    c.execute(query)
    results = c.fetchmany(amount)
    count = 0
    # Loop through the returned rows and format the message
    while count < len(results) and count < 5:
        user_id = results[count][0]
        username = user_ids[user_id] # used so we don't tag everyone
        score = results[count][1]
        message += '\n{} - *@{}*: {}'.format(
                count+1, username, score)
        count += 1
    return message


def handle_lookup_others(amount):
    '''
    Find a given amount of arbitrary text and their scores from the OtherScores
    table. If amount < 0, we need to find the lowest scores. Returns a string
    with the formatted data.
    '''
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    query = 'SELECT * FROM OtherScores ORDER By Score'
    # We need the top 5 scores
    if amount > 0:
        query += ' DESC'
    message = '*Other leaderboard*'
    c.execute(query)
    results = c.fetchmany(amount)
    count = 0
    # Loop through the returned rows and format the message
    while count < len(results) and count < 5:
        text = results[count][0]
        score = results[count][1]
        message += '\n{} - *@{}*: {}'.format(
                count+1, text, score)
        count += 1
    return message


def handle_lookup_one(subject):
    '''
    Find the score for a given subject. First decides whether it is a user or
    an "other", then queries the appropriate table. Returns the subject's score.
    '''
    table = ''
    column = ''
    # subject is a user
    if re.match('<@[A-Za-z0-9]+>', subject):
        table = 'UserScores'
        column = 'User'
        subject = re.sub('[<@>]', '', subject)
    # subject is not a user
    else:
        table = 'OtherScores'
        column = 'Name'
        subject = re.sub('@', '', subject)
    subject_param = (subject,)
    query = 'SELECT * FROM {} WHERE {} = ?'.format(table, column)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(query, (subject_param))
    result = c.fetchone()
    if not result:
        result = [subject, 0] # user is not in the database
    return result[1] # only need the score


def print_help(channel):
    '''
    Print a help message showing how to use the commands
    '''
    message = "Here is a list of commands you can use with <@{0}> by typing " \
              "<@{0}> [command]:"
    message += '''
    *leaderboard | top*: Show the top five scoring users and other objects
    *bottom*: Show the bottom five scoring users and other objects
    *lookup [user|object]*: Lookup the current score for the user or object
        '''
    post_message(message.format(bot_id), channel)


def post_message(message, channel):
    '''
    Post a given message to the given channel
    '''
    slack_client.api_call(
            'chat.postMessage',
            channel=channel,
            text=message
    )


def init_user_dict():
    '''
    Calls the 'users.list' function to get a dictionary of all the user info. 
    Use that information to populate the user_ids dict with user_id: username
    pairs. This lets us use the person's username without tagging them.
    '''
    request = slack_client.api_call('users.list')
    if request['ok']:
        for item in request['members']:
            user_ids[item['id']] = item['name']


if __name__ == '__main__':
    if slack_client.rtm_connect(with_team_state=False):
        print('PlusPlusBot connected and running')
        # read bot's user ID by calling Web API method 'auth.test'
        bot_id = slack_client.api_call('auth.test')['user_id']
        # initialize regex with the bot id
        BOT_MENTION_REGEX = BOT_MENTION_REGEX.format(bot_id)
        init_user_dict()
        while True:
            mentions, others, channel = parse_messages(slack_client.rtm_read())
            if mentions:
                handle_plusplus_mentions(mentions, channel)
            if others:
                handle_plusplus_others(others, channel)
            time.sleep(RTM_READ_DELAY)
    else:
        print('connection failed. exception trace printed above')
