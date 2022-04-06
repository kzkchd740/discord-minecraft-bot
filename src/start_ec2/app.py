import json
import os
import time
import requests
import datetime
import pytz

import boto3

EC2_INSTANCE_ID = os.getenv('EC2_INSTANCE_ID')

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
COMMAND_CHANNEL_ID = os.getenv('COMMAND_CHANNEL_ID')
MONITERING_EVENT_NAME = os.getenv('MONITERING_EVENT_NAME')

DISCORD_ENDPOINT = f"https://discordapp.com/api/channels/{COMMAND_CHANNEL_ID}/messages"

MAINTENANCE_START_TIME = datetime.time(5, 0, 0)  # メンテナンス開始時間
MAINTENANCE_END_TIME = datetime.time(5, 59, 59)  # メンテナンス終了時間


def lambda_handler(event, context):
    title = ""

    try:
        # インスタンスのステータスを取得
        region = os.environ['AWS_REGION']
        ec2_client = boto3.client('ec2', region_name=region)
        ec2_resource = boto3.resource('ec2').Instance(EC2_INSTANCE_ID)
        status_response = ec2_client.describe_instances(InstanceIds=[EC2_INSTANCE_ID])

        ec2_status = status_response['Reservations'][0]['Instances'][0]['State']['Name']
        print('[INFO] Instance Status:' + str(ec2_status))

        if ec2_status == "running":
            # 起動済み
            title = "サーバーは起動済みだよ！"
        else:
            # 東京タイムゾーンの日時を取得
            tokyo_now = datetime.datetime.now(pytz.timezone('Asia/Tokyo'))
            tokyo_time = tokyo_now.time()

            # メンテナンス時間内ならec2を起動しない
            if (MAINTENANCE_START_TIME < tokyo_time) & (MAINTENANCE_END_TIME > tokyo_time):
                send_message('\N{WARNING SIGN} ただいまメンテナンス中！',
                             f'{MAINTENANCE_START_TIME}～{MAINTENANCE_END_TIME}はメンテナンス中です \N{PERSON BOWING DEEPLY} ',
                             16705372)

                return 0

            # EC2起動
            response = ec2_client.start_instances(InstanceIds=[EC2_INSTANCE_ID])
            print('[INFO] Instance' + str(response))
            ec2_resource.wait_until_running()

            # EC2起動が完了するまで待機
            cont = 1
            total = 0

            while cont:
                status_response = ec2_client.describe_instance_status(InstanceIds=[EC2_INSTANCE_ID])
                if (status_response['InstanceStatuses'][0]['InstanceStatus']['Status'] == "ok" and
                        status_response['InstanceStatuses'][0]['SystemStatus']['Status'] == "ok"):
                    cont = 0
                else:
                    time.sleep(5)
                    total += 5
            print('[INFO] Successfully Started Instance: ' + str(EC2_INSTANCE_ID) + ' wait time was roughly: ' +
                  str(total) + 'seconds.')

            # マイクラ起動
            ssm_client = boto3.client('ssm')
            ssm_response = ssm_client.send_command(
                InstanceIds=[EC2_INSTANCE_ID],
                DocumentName="AWS-RunShellScript",
                Parameters={
                    "commands": ["cd /home/ec2-user/minecraft/", "sh Minecraft_start.sh"]
                }
            )

            # コマンドIDを取得
            command_id = ssm_response['Command']['CommandId']

            # 開始スクリプトの実行状況を確認
            time.sleep(2)
            command_invocation_result = \
                ssm_client.get_command_invocation(CommandId=command_id, InstanceId=EC2_INSTANCE_ID)
            status = command_invocation_result['Status']

            if status == "Failed":
                raise Exception('Failed Started Minecraft.')
            elif status == "TimedOut":
                raise TimeoutError('Timeout Started Minecraft.')
            else:
                print('[INFO] Successfully Started Minecraft.')

            # マイクラが開始するまで待機
            time.sleep(15)

            # EC2監視イベントの有効化
            events_client = boto3.client('events')
            response = events_client.enable_rule(
                Name=MONITERING_EVENT_NAME
            )

            print('[INFO] Successfully Started Minecraft.')
            title = "\N{WHITE HEAVY CHECK MARK} サーバー起動完了！"

        # public ip取得
        instance_response = ec2_client.describe_instances(InstanceIds=[EC2_INSTANCE_ID])
        public_ip = instance_response['Reservations'][0]['Instances'][0]['PublicIpAddress']
        print('[LOG] public_ip: ' + public_ip)

        mag = f"IPアドレス: 【{public_ip}】"

        send_message(title, mag)
        return 0

    except Exception as error:
        print('[ERROR] ' + str(error))
        send_message('\N{cross mark} サーバー起動失敗！', '管理者に問い合わせてね\N{Person with Folded Hands}', 15548997)
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
