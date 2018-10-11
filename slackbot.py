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
EXAMPLE_COMMAND = 'do'
MENTION_REGEX = '^<@(|[WU].+?)>(.*)'
PLUSPLUS_REGEX = '<@(|[WU].+?)>\s?[+]{2}'


def parse_bot_commands(slack_events):
    '''
    Parse a list of events c oming from the Slack RTM API to find bot
    commands. If a bot command is found, this function returns a tuple
    of command and channel. If it is not found, then this function
    returns None, None.
    '''
    for event in slack_events:
        if event['type'] == 'message' and not 'subtype' in event:
            '''
            user_id, message = parse_direct_mention(event['text'])
            if user_id == bot_id:
                return message, event['channel']
            '''
            user_id = parse_direct_mention(event['text'])
            print('user: {}'.format(user_id))
            return user_id, event['channel']
    return None, None


def parse_direct_mention(message_text):
    '''
    Find a direct mention (at the beginning) in message text and returns
    the user ID which was mentioned. If there is no direct mention,
    returns None.
    '''
    print('message: {}'.format(message_text))
    pp_matches = re.search(PLUSPLUS_REGEX, message_text)
    return pp_matches.group(1) if pp_matches else None
    '''
    matches = re.search(MENTION_REGEX, message_text)
    # first group contains username, second contains remaining message
    if (matches):
        return (matches.group(1), matches.group(2).strip()
    else:
        return (None, None)
    '''


def handle_command(command, channel):
    '''
    Execute bot command if the command is known
    '''
    # Default response is help text for the user
    default_response = 'Not sure what you mean. Try *{}*'.format(
            EXAMPLE_COMMAND)

    # Finds and executes the given command, filling in response
    response = None
    # put in more commands
    if command.startswith(EXAMPLE_COMMAND):
        response = 'write more code to do the thing'

    # send response to the channel
    slack_client.api_call(
            'chat.postMessage',
            channel=channel,
            text=response or default_response
    )


def handle_plusplus(user_id, channel):
    slack_client.api_call(
            'chat.postMessage',
            channel=channel,
            text='{} got a plusplus'.format(user_id)
    )


if __name__ == '__main__':
    if slack_client.rtm_connect(with_team_state=False):
        print('bot connected and running')
        # read bot's user ID by calling Web API method 'auth.test'
        bot_id = slack_client.api_call('auth.test')['user_id']
        while True:
            '''
            command, channel = parse_bot_commands(slack_client.rtm_read())
            if command:
                handle_command(command,channel)
            '''
            user_id, channel = parse_bot_commands(slack_client.rtm_read())
            if user_id:
                handle_plusplus(user_id, channel)
            time.sleep(RTM_READ_DELAY)
    else:
        print('connection failed. exception trace printed above')
