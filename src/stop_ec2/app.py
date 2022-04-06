import json
import os
import time
import requests

import boto3

EC2_INSTANCE_ID = os.getenv('EC2_INSTANCE_ID')

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
COMMAND_CHANNEL_ID = os.getenv('COMMAND_CHANNEL_ID')
MONITERING_EVENT_NAME = os.getenv('MONITERING_EVENT_NAME')

DISCORD_ENDPOINT = f"https://discordapp.com/api/channels/{COMMAND_CHANNEL_ID}/messages"


def lambda_handler(event, context):
    try:
        # インスタンスのステータスを取得
        region = os.environ['AWS_REGION']
        ec2_client = boto3.client('ec2', region_name=region)
        ec2_resource = boto3.resource('ec2').Instance(EC2_INSTANCE_ID)
        status_response = ec2_client.describe_instances(InstanceIds=[EC2_INSTANCE_ID])

        ec2_status = status_response['Reservations'][0]['Instances'][0]['State']['Name']
        print('[INFO] Instance Status:' + str(ec2_status))

        if ec2_status == "shutting-down" or ec2_status == "stopped":
            # 停止済み
            send_message("サーバーはもう停止してるよ！", '', 16705372)
            return 0
        else:
            # マイクラ終了
            ssm_client = boto3.client('ssm')
            ssm_response = ssm_client.send_command(
                InstanceIds=[EC2_INSTANCE_ID],
                DocumentName="AWS-RunShellScript",
                Parameters={
                    "commands": ["cd /home/ec2-user/minecraft/", "sh Minecraft_stop.sh"]
                }
            )

            # コマンドIDを取得
            command_id = ssm_response['Command']['CommandId']

            # 終了スクリプトの実行状況を確認
            time.sleep(2)
            command_invocation_result = \
                ssm_client.get_command_invocation(CommandId=command_id, InstanceId=EC2_INSTANCE_ID)
            status = command_invocation_result['Status']

            if status == "Failed":
                raise Exception('Failed Stopped Minecraft.')
            elif status == "TimedOut":
                raise TimeoutError('Timeout Stopped Minecraft.')
            else:
                print('[INFO] Successfully Stopped Minecraft.')

            # マイクラが完了するまで待機
            time.sleep(55)

            # EC2停止
            response = ec2_client.stop_instances(InstanceIds=[EC2_INSTANCE_ID])
            print('[INFO] Successfully Instance: ' + str(EC2_INSTANCE_ID))

            # EC2監視イベントの無効化
            events_client = boto3.client('events')
            response = events_client.disable_rule(
                Name=MONITERING_EVENT_NAME
            )

        send_message('\N{WHITE HEAVY CHECK MARK} サーバー停止しました', 'お疲れ様！')
        return 0

    except Exception as error:
        print('[ERROR] ' + str(error))
        send_message('\N{cross mark} サーバー停止失敗！', '管理者に問い合わせてね\N{Person with Folded Hands}', 15548997)
        return 0


def send_message(title, msg, color=5763719):
    body = {
        "embeds": [
            {
                "title": title,
                "description": msg,
                "color": color
            }
        ]
    }

    headers = {
        "Authorization": f"Bot {DISCORD_TOKEN}",
    }

    response = requests.post(DISCORD_ENDPOINT, json=body, headers=headers)
    print('[INFO] Send Message:' + str(response))
