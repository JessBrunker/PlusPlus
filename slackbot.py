#!/usr/bin/python3

import os
import time
import re
import sqlite3

from slackclient import SlackClient


# instantiate Slack client
slack_client = SlackClient(
        'xoxb-453319474130-452584383648-nndKenwwf4UEsrPl1HRStZ5s')
# bot's user ID in Slack: value assigned after startup
bot_id = None

# constants
RTM_READ_DELAY = 1 # 1 second delay between reading from RTM
USER_PP_REGEX = '<@(|[WU].+?)>\s?([+-]){2}' # finds @user++
OTHER_PP_REGEX = '@(\S+)\s?([+-]){2}' # finds @anything++


def parse_messages(slack_events):
    '''
    Parse incoming messages looking for instances of ++ or --. Returns a
    list of tuples of the form (username, plus/minus), and the channel in
    which the mention appeared. Returns None, None if nothing is found.
    '''
    for event in slack_events:
        if event['type'] == 'message' and not 'subtype' in event:
            #pp_mentions = parse_plusplus_mentions(event['text'])
            pp_mentions = re.findall(USER_PP_REGEX, event['text'])
            pp_mentions = set(pp_mentions) # remove duplicates
            pp_others = re.findall(OTHER_PP_REGEX, event['text'])
            pp_others = set(filter(
                lambda x: x not in pp_mentions, pp_others))
            return pp_mentions, pp_others, event['channel']
    return None, None, None


def handle_plusplus_mentions(mentions, channel):
    '''
    Increment a user's point value if the symbol is a '+', and decrement
    the user's point value if the symbol is a '-'. Print out the user's
    total after the operation is complete.
    '''
    conn = sqlite3.connect('scores.db')
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
        slack_client.api_call(
            'chat.postMessage',
            channel=channel,
            text='<@{}> total points: {}'.format(
                user_values[0], user_values[1])
        )
    conn.commit()


def handle_plusplus_others(pp_instances, channel):
    conn = sqlite3.connect('scores.db')
    c = conn.cursor()
    for instance in pp_instances:
        name, symbol = instance
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
            c.execute('''UPDATE UserScores SET Score = ?
                WHERE User = ?''', (name_values[1], name_values[0]))
        slack_client.api_call(
                'chat.postMessage',
                channel=channel,
                text='@{} total points: {}'.format(
                    name_values[0], name_values[1])
        )
    conn.commit()


if __name__ == '__main__':
    if slack_client.rtm_connect(with_team_state=False):
        print('bot connected and running')
        # read bot's user ID by calling Web API method 'auth.test'
        bot_id = slack_client.api_call('auth.test')['user_id']
        while True:
            mentions, others, channel = parse_messages(slack_client.rtm_read())
            if mentions:
                handle_plusplus_mentions(mentions, channel)
            if others:
                handle_plusplus_others(others, channel)
            time.sleep(RTM_READ_DELAY)
    else:
        print('connection failed. exception trace printed above')
