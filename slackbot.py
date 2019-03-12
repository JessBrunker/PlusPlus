#!/usr/bin/python3

import os
import time
import re
import sqlite3

from slackclient import SlackClient
from slack_code import wsd_code
from slack_code import test_code


# set to false if not using test slack
TESTING = False

# instantiate Slack client
slack_client = None
if TESTING:
    slack_client = SlackClient(test_code)
else:
    slack_client = SlackClient(wsd_code)

# bot's user ID in Slack: value assigned after startup
bot_id = None
# dict for user_id: username pairs
user_ids = {}

# constants
RTM_READ_DELAY = 1  # 1 second delay between reading from RTM
# Finds bot commands e.g. @bot help
BOT_MENTION_REGEX = '^<@{}>\s([A-Za-z0-9\s]+)\s?(\S+)?$'
USER_PP_REGEX = '<@(|[WU]\w+?)>\s?([+-]{2})'  # finds @user++
OTHER_PP_REGEX = '@\s?([-_A-Za-z0-9:#]+[^>])\s?([+-]{2})'  # finds @anything++
DB_FILE = 'scores.db'


def parse_messages(slack_events):
    '''
    Parses incoming slack events for user mentions, other mentions, and bot commands,
    and acts accordingly. If there is a bot command, the function ends after its
    resolution.
    '''
    for event in slack_events:
        if event['type'] == 'message' and not 'subtype' in event:
            # check for '@bot {command}
            command_matches = re.search(BOT_MENTION_REGEX, event['text'])
            if command_matches and command_matches.group(1):
                bot_command = command_matches.group(1)
                parameters = command_matches.group(2)
                handle_command(bot_command, parameters, event['channel'])
                # return None, None, None # do not allow ++ in a bot command
                return

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
            handle_plusplus_mentions(event['user'], pp_mentions, event['channel'])

            # check for @nonuser++
            pp_others = re.findall(OTHER_PP_REGEX, event['text'])
            # want to exclude any entries that are actually usernames
            pp_others = set(filter(
                lambda x: x not in pp_mentions, pp_others))
            handle_plusplus_others(pp_others, event['channel'])

            # return pp_mentions, pp_others, event['channel']
    # return None, None, None


def self_gratification(user, mentions):
    '''
    Returns True if the user is trying to give themselves a plusplus
    '''
    for mention in mentions:
        if user == mention[0]:
            return True
    return False


def handle_plusplus_mentions(user, mentions, channel):
    '''
    Increment a user's point value if the symbol is a '+', and decrement
    the user's point value if the symbol is a '-' and update the values in
    the database. Print out the user's total after the operation is complete.
    Additionally update the original user's +/- differential.
    '''
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    user_diff = 0  # used to track user +/- differential
    for mention in mentions:
        recip_id, symbol = mention
        recip = (recip_id,)  # used to prevent SQL injections
        c.execute('''SELECT User, Score FROM UserScores
                    WHERE User = ?''', recip)
        recip_values = c.fetchone()
        if symbol == '++':
            user_diff += 1
        elif symbol == '--':
            user_diff -= 1
        else:
            continue

        if not recip_values:  # user isn't in table yet
            init_points = 1 if symbol == '+' else -1
            recip_values = (recip_id, init_points, 0)
            c.execute('INSERT INTO UserScores VALUES (?, ?, ?)', recip_values)
        else:
            score = recip_values[1]
            if symbol == '++':
                score += 1
            elif symbol == '--':
                score -= 1
            else:
                continue
            recip_values = (recip_id, score)
            # need to reverse the tuple to fit the query
            c.execute('''UPDATE UserScores SET Score = ?
                    WHERE User = ?''', (recip_values[1], recip_values[0]))
        post_message('<@{}> total points: {}'.format(
            recip_values[0], recip_values[1]), channel)
    # update user differential
    if user_diff != 0:
        user_param = (user,)
        c.execute('''SELECT User, Differential FROM UserScores
                    WHERE User = ?''', user_param)
        user_values = c.fetchone()
        if not user_values:  # user not in table
            c.execute('INSERT INTO UserScores VALUES (?, ?, ?)',
                      (user, 0, user_diff))
        else:
            score = user_values[1]
            score += user_diff
            c.execute('''UPDATE UserScores SET Differential = ?
                    WHERE User = ?''', (score, user))
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
        name_tup = (name,)  # prevent SQL injections
        c.execute('''SELECT Name, Score FROM OtherScores
            WHERE Name = ?''', name_tup)
        name_values = c.fetchone()

        if not name_values:  # name isn't in table yet
            init_points = 1 if symbol == '++' else -1
            if symbol == '++':
                init_point = 1
            elif symbol == '--':
                init_point = -1
            else:
                continue
            name_values = (name, init_points)
            c.execute('INSERT INTO OtherScores VALUES (?, ?)', name_values)
        else:
            score = name_values[1]
            if symbol == '++':
                score += 1
            elif symbol == '--':
                score -= 1
            else:
                continue

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
            result, diff = handle_lookup_one(subject)
            message = '{} has {} points'.format(subject, result)
            if diff is not None:
                message += ' and has a ++/-- ratio of {0:+d}'.format(diff)
        else:
            message = 'I don\'t know who you want me to lookup. " \
            "Type "<@{0}> lookup @user" or "<@{0}> lookup @text"'.format(bot_id)
    # Show the bottom 5 scores in both tables
    elif command in ['loserboard', 'bottom']:
        message = handle_lookup_users(-5)
        message += '\n\n'
        message += handle_lookup_others(-5)
    # Show the top 5 highest +/- differentials
    elif command in ['nicest', 'givers', 'diff', 'differential']:
        message = handle_lookup_diff(5)
    # Show the bottom 5 +/- differentials
    elif command in ['worst', 'takers']:
        message = handle_lookup_diff(-5)
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
    query = 'SELECT User, Score FROM UserScores ORDER BY Score'
    message = ''
    # We need the top 5 scores
    if amount > 0:
        query += ' DESC'
        message = '*Users leaderboard*'
    else:
        message = '*Users loserboard*'
    c.execute(query)
    results = c.fetchmany(amount)
    count = 0
    prev_score = results[0][1]  # top score
    position = 1
    # Loop through the returned rows and format the message
    while count < len(results) and count < 5:
        user_id = results[count][0]
        username = user_ids[user_id]  # used so we don't tag everyone
        score = results[count][1]
        if score != prev_score:  # resolve ties
            position = count+1
        prev_score = score
        message += '\n{} - *@{}*: {}'.format(
            position, username, score)
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
    message = ''
    # We need the top 5 scores
    if amount > 0:
        query += ' DESC'
        message = '*Other leaderboard*'
    else:
        message = '*Other loserboard*'
    c.execute(query)
    results = c.fetchmany(amount)
    count = 0
    prev_score = results[0][1]  # top score
    position = 1
    # Loop through the returned rows and format the message
    while count < len(results) and count < 5:
        text = results[count][0]
        score = results[count][1]
        if score != prev_score:  # resolve ties
            position = count+1
        prev_score = score
        message += '\n{} - *@{}*: {}'.format(
            position, text, score)
        count += 1
    return message


def handle_lookup_diff(amount):
    '''
    Find a given amount of users, ordered by their ++/-- differential. If amount < 0,
    we need the lowest scores. Returns a string with formatted data.
    '''
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    query = 'SELECT User, Differential FROM UserScores ORDER BY Differential'
    # Highest 5 diff
    if amount > 0:
        query += ' DESC'
        message = '*Top ++ givers*'
    else:
        message = '*Top -- givers*'
    c.execute(query)
    results = c.fetchmany(amount)
    count = 0
    prev_diff = results[0][1]  # top diff
    position = 1
    # Loop through the returned rows and format the message
    while count < len(results) and count < 5:
        user_id = results[count][0]
        username = user_ids[user_id]  # used so we don't tag everyone
        diff = results[count][1]
        if diff != prev_diff:  # resolve ties
            position = count+1
        prev_diff = diff
        message += '\n{} - *@{}*: {}'.format(
            position, username, diff)
        count += 1
    return message


def handle_lookup_one(subject):
    '''
    Find the score for a given subject. First decides whether it is a user or
    an "other", then queries the appropriate table. Returns the subject's score, also
    returns the differential if the subject is a user.
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
    if not result and column == 'User':
        result = (subject, 0, 0)  # user is not in the database
        c.execute('INSERT INTO UserScores VALUES (?, ?, ?)', result)
        conn.commit()
    if column == 'User':
        return result[1], result[2]
    else:
        return result[1], None


def print_help(channel):
    '''
    Print a help message showing how to use the commands
    '''
    message = "Here is a list of commands you can use with <@{0}> by typing " \
              "<@{0}> [command]:"
    message += '''
    *leaderboard | top*: Show the top five scoring users and other objects
    *loserboard | bottom*: Show the bottom five scoring users and other objects
    *lookup [user|object]*: Look up the current score for the user or object
    *givers*: Look who has given out the most ++
    *takers*: Look who has given out the most --
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
    if slack_client.rtm_connect(with_team_state=False, auto_reconnect=True):
        print('PlusPlusBot connected and running')
        # read bot's user ID by calling Web API method 'auth.test'
        bot_id = slack_client.api_call('auth.test')['user_id']
        # initialize regex with the bot id
        BOT_MENTION_REGEX = BOT_MENTION_REGEX.format(bot_id)
        init_user_dict()
        while True:
            parse_messages(slack_client.rtm_read())
            time.sleep(RTM_READ_DELAY)
    else:
        print('connection failed. exception trace printed above')
