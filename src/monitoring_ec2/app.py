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
STACK_NAME = os.getenv('STACK_NAME')

DISCORD_ENDPOINT = f"https://discordapp.com/api/channels/{COMMAND_CHANNEL_ID}/messages"

MAINTENANCE_START_TIME = datetime.time(5, 0, 0)  # メンテナンス開始時間
MAINTENANCE_END_TIME = datetime.time(5, 59, 59)  # メンテナンス終了時間


def lambda_handler(event, context):
    try:
        dt_now = datetime.datetime.now()  # 現時刻

        # インスタンスのステータスを取得
        region = os.environ['AWS_REGION']
        ec2_client = boto3.client('ec2', region_name=region)
        ec2_resource = boto3.resource('ec2').Instance(EC2_INSTANCE_ID)
        status_response = ec2_client.describe_instances(InstanceIds=[EC2_INSTANCE_ID])

        ec2_status = status_response['Reservations'][0]['Instances'][0]['State']['Name']
        print('[INFO] Instance Status:' + str(ec2_status))

        if ec2_status != "running":
            # 起動していなければチェックしない
            return 0
        else:
            # 東京タイムゾーンの日時を取得
            tokyo_now = datetime.datetime.now(pytz.timezone('Asia/Tokyo'))
            tokyo_time = tokyo_now.time()

            # メンテナンス時間内ならec2をシャットダウン
            if (MAINTENANCE_START_TIME < tokyo_time) & (MAINTENANCE_END_TIME > tokyo_time):
                send_title = '\N{WARNING SIGN} メンテナンス開始したので、サーバー停止しました'
                send_msg = f'{MAINTENANCE_START_TIME}～{MAINTENANCE_END_TIME}はメンテナンス中です \N{PERSON BOWING DEEPLY} '

                # マイクラ終了
                shutdown_ec2(ec2_client, send_title, send_msg)

                return 0

            # マイクラサーバー監視ログを取得する為のコマンドを実行
            ssm_client = boto3.client('ssm')
            ssm_response = ssm_client.send_command(
                InstanceIds=[EC2_INSTANCE_ID],
                DocumentName="AWS-RunShellScript",
                Parameters={
                    "commands":
                        [
                            "uptime -s",  # 起動時間
                            "who -q",  # ec2にログイン中のユーザー情報
                            "cat /home/ec2-user/minecraft/plugins/Zabbigot/status.json"  # マイクラサーバーを監視ログ
                        ]
                },
                CloudWatchOutputConfig={
                    "CloudWatchLogGroupName": "minecraft_server_logs",
                    "CloudWatchOutputEnabled": True
                },
                TimeoutSeconds=60
            )
            command_id = ssm_response['Command']['CommandId']

            # 開始スクリプトの実行状況を確認
            time.sleep(2)
            command_invocation_result = \
                ssm_client.get_command_invocation(CommandId=command_id, InstanceId=EC2_INSTANCE_ID)
            status = command_invocation_result['Status']

            if status == "Failed":
                raise Exception('Failed Started Command.')
            elif status == "TimedOut":
                raise TimeoutError('Timeout Started Command.')

            # 監視ログを取得
            logs_client = boto3.client('logs')
            logs_response = logs_client.describe_log_streams(
                logGroupName='minecraft_server_logs',
                orderBy='LastEventTime',
                descending=True,
            )

            stream_list = []
            for stream in logs_response['logStreams']:
                stream_list.append(stream['logStreamName'])

            print(stream_list)

            logs = logs_client.get_log_events(
                logGroupName="minecraft_server_logs",
                logStreamName=stream_list[0],
                startFromHead=True
            )

            logs_message = logs['events'][0]['message']
            log_list = logs_message.splitlines()

            # ec2起動日時
            dt_uptime = datetime.datetime.strptime(log_list[0], '%Y-%m-%d %H:%M:%S')

            # 起動時間(分)を取得
            delta = dt_now - dt_uptime
            m_delta = int(delta.seconds / 60)

            # ec2にログイン中のユーザー数
            login_user_cnt = int(log_list[2].replace('# users=', ''))

            # マイクラログ
            minecraft_log = json.loads(log_list[3])
            minecraft_login_user_cnt = int(minecraft_log['user'])

            '''
            以下の条件を満たす場合、ec2をシャットダウンする
            
            1.ec2の起動時間が30分以上
            2.ec2のログイン人数が0人
            3.マイクラのログイン人数が0人
            '''
            if (m_delta > 30) & (login_user_cnt == 0) & (minecraft_login_user_cnt == 0):
                send_title = '\N{WHITE HEAVY CHECK MARK} サーバー自動停止しました'
                send_msg = 'お疲れ様！'

                # マイクラ終了
                shutdown_ec2(ec2_client, send_title, send_msg)

        return 0

    except Exception as error:
        print('[ERROR] ' + str(error))
        return 0


def shutdown_ec2(ec2_client, send_title, send_msg):
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
    print('[INFO] Successfully Stopped Instance: ' + str(EC2_INSTANCE_ID))

    events_client = boto3.client('events')

    # 監視イベント名を取得(templateからテンプレートを取得するとリソース間の循環依存関係が発生)
    response = events_client.list_rules(
        NamePrefix=STACK_NAME,
        Limit=1
    )
    event_name = response['Rules'][0]['Name']

    # EC2監視イベントの無効化
    response = events_client.disable_rule(
        Name=event_name
    )

    send_message(send_title, send_msg)


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
