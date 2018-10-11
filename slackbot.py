#!/usr/bin/python3

import os
import time
import re

from slackclient import SlackClient


# instantiate Slack client
slack_client = SlackClient(
        'xoxb-453319474130-452584383648-nndKenwwf4UEsrPl1HRStZ5s')
# bot's user ID in Slack: value assigned after startup
bot_id = None

# constants
RTM_READ_DELAY = 1 # 1 second delay between reading from RTM
PLUSPLUS_REGEX = '<@(|[WU].+?)>\s?([+-]){2}'


def parse_messages(slack_events):
    '''
    Parse incoming messages looking for instances of ++ or --. Returns a
    list of tuples of the form (username, plus/minus), and the channel in
    which the mention appeared. Returns None, None if nothing is found.
    '''
    for event in slack_events:
        if event['type'] == 'message' and not 'subtype' in event:
            pp_mentions = parse_plusplus_mentions(event['text'])
            return pp_mentions, event['channel']
    return None, None


def parse_plusplus_mentions(message_text):
    '''
    Search a given message and return all instances that match
    PLUSPLUS_REGEX (text that matches @username++). Returns a tuple with
    the username and whether it was a ++ or --.
    '''
    pp_matches = re.findall(PLUSPLUS_REGEX, message_text)
    return pp_matches


def handle_plusplus(user_id, symbol, channel):
    '''
    Increment a user's point value if the symbol is a '+', and decrement
    the user's point value if the symbol is a '-'. Print out the user's
    total after the operation is complete.
    '''
    text = '++' if symbol == '+' else '--'
    slack_client.api_call(
            'chat.postMessage',
            channel=channel,
            # still need to connect to database, for now just print
            text='<@{}> got a {}'.format(user_id, text)
    )


if __name__ == '__main__':
    if slack_client.rtm_connect(with_team_state=False):
        print('bot connected and running')
        # read bot's user ID by calling Web API method 'auth.test'
        bot_id = slack_client.api_call('auth.test')['user_id']
        while True:
            mentions, channel = parse_messages(slack_client.rtm_read())
            if mentions:
                for mention in mentions:
                    handle_plusplus(mention[0], mention[1], channel)
            time.sleep(RTM_READ_DELAY)
    else:
        print('connection failed. exception trace printed above')
