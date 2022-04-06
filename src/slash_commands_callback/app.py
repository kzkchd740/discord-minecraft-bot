import json
import os
import boto3

from nacl.signing import VerifyKey

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
APPLICATION_ID = os.getenv('APPLICATION_ID')
APPLICATION_PUBLIC_KEY = os.getenv('APPLICATION_PUBLIC_KEY')
COMMAND_GUILD_ID = os.getenv('COMMAND_GUILD_ID')

verify_key = VerifyKey(bytes.fromhex(APPLICATION_PUBLIC_KEY))


def verify(signature: str, timestamp: str, body: str) -> bool:
    try:
        verify_key.verify(f"{timestamp}{body}".encode(), bytes.fromhex(signature))
    except Exception as e:
        print(f"failed to verify request: {e}")
        return False

    return True


def lambda_handler(event: dict, context: dict):
    # API Gateway has weird case conversion, so we need to make them lowercase.
    # See https://github.com/aws/aws-sam-cli/issues/1860
    headers: dict = {k.lower(): v for k, v in event['headers'].items()}
    rawBody: str = event['body']

    # validate request
    signature = headers.get('x-signature-ed25519')
    timestamp = headers.get('x-signature-timestamp')
    if not verify(signature, timestamp, rawBody):
        return {
            "cookies": [],
            "isBase64Encoded": False,
            "statusCode": 401,
            "headers": {},
            "body": ""
        }

    req: dict = json.loads(rawBody)
    if req['type'] == 1:  # InteractionType.Ping
        return {
            "type": 1  # InteractionResponseType.Pong
        }
    elif req['type'] == 2:  # InteractionType.ApplicationCommand
        # command options list -> dict
        opts = {v['name']: v['value'] for v in req['data']['options']} if 'options' in req['data'] else {}
        action = req['data']['options'][0]['value']
        username = req['member']['user']['username']

        title = ""
        msg = ""

        if action == 'start':
            client = boto3.client('lambda')
            client.invoke(
                FunctionName=os.getenv('START_EC2_LAMBDA_FUNCTION'),
                InvocationType='Event'
            )
            title = "サーバーを起動します!"
            msg = "\N{timer clock}３分ぐらい待ってね"

        if action == 'stop':
            client = boto3.client('lambda')
            client.invoke(
                FunctionName=os.getenv('STOP_EC2_LAMBDA_FUNCTION'),
                InvocationType='Event'
            )
            title = "サーバーを停止します!"
            msg = "\N{timer clock}2分ぐらい待ってね"

        if action == 'restart':
            client = boto3.client('lambda')
            client.invoke(
                FunctionName=os.getenv('RESTART_EC2_LAMBDA_FUNCTION'),
                InvocationType='Event'
            )
            title = "サーバーを再起動します!"
            msg = "\N{timer clock}３分ぐらい待ってね"

        return {
            "type": 4,  # InteractionResponseType.ChannelMessageWithSource
            "data": {
                "embeds": [
                    {
                        "title": title,
                        "description": msg,
                        "color": 16777215
                    }
                ]
            }
        }
