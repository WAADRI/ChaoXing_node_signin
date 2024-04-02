from email.mime.text import MIMEText
from email.utils import formataddr
from hashlib import md5


import asyncio
import base64
import datetime
import json
import logging
import os
import random
import re
import subprocess
import sys
import time
import urllib.parse
import uuid

package_install = False
required_packages = ["aiofiles", "aiohttp", "aiosmtplib", "portalocker", "websockets", "yaml", "Crypto"]
install_packages = ["aiofiles", "aiohttp", "portalocker", "websockets", "aiosmtplib", "pyyaml", "pycryptodome"]


def install(_package):
    subprocess.check_call([sys.executable, "-m", "pip", "install", _package, "-i", "https://pypi.mirrors.ustc.edu.cn/simple/"])
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.info("开始检查第三方库安装情况")
for p in range(len(required_packages)):
    try:
        __import__(required_packages[p])
        logging.info(f"第三方库“{install_packages[p]}”已安装")
    except ImportError:
        package_install = True
        logging.info(f"第三方库“{install_packages[p]}”未安装，开始安装")
        install(install_packages[p])
if package_install:
    logging.info("第三方库安装完成，程序即将重新启动")
    os.execl(sys.executable, sys.executable, *sys.argv)

import aiofiles
import aiohttp
import aiosmtplib
import portalocker
import websockets
import yaml
from Crypto.Cipher import AES


class ColoredFormatter(logging.Formatter):
    COLOR_CODES = {
        logging.DEBUG: "\033[94m",  # 蓝色
        logging.INFO: "\033[92m",   # 绿色
        logging.WARNING: "\033[93m",  # 黄色
        logging.ERROR: "\033[91m",    # 红色
        logging.CRITICAL: "\033[1;91m"  # 亮红色
    }
    RESET_CODE = "\033[0m"

    def format(self, record):
        msg = super().format(record)
        color_code = self.COLOR_CODES.get(record.levelno, "")
        return f"{color_code}{msg}{self.RESET_CODE}"

realpath = os.path.dirname(sys.argv[0])
config_path = os.path.join(realpath, "node_config.yaml")
if os.path.isfile(config_path):
    with open(config_path) as file:
        config = yaml.safe_load(file)
        node_name = config["node"]["name"]
        node_password = config["node"]["password"]
        email_address = config["email"]["address"]
        email_password = config["email"]["password"]
        email_use_tls = config["email"]["use_tls"]
        email_host = config["email"]["host"]
        email_port = config["email"]["port"]
        email_user = config["email"]["user"]
        node_debug = config["debug"]
        node_uuid = config["uuid"]
else:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.warning('未检测到节点配置文件，将会自动在当前路径下生成默认配置文件，请稍后自行修改配置文件后再次运行本程序')
    time.sleep(3)
    with open(config_path, "w") as file:
        data = '''# 邮件功能配置区
email:
  # 用来发送邮件的邮箱，未填写则不发送邮件
  address: ''
  # 用来发送邮件的邮箱密码
  password: ''
  # 是否使用tls加密连接，默认为true
  use_tls: true
  # 邮件服务器的host主机名
  host: ''
  # 邮件服务器端口
  port: ''
  # 发件人名称
  user: ''
# 节点名称密码配置区
node:
  # 节点名称，不能和已接入在线自动签到系统的其它自建节点名称重复
  name: ''
  # 节点密码，设置后用户需要在网站中输入正确的密码才能使用该节点，留空则为不设置密码，此时任何人均可使用该节点进行签到
  password: ''
# 是否启用debug模式，启用后日志输出更加详细，方便排查问题，建议使用时出现问题且命令行中未展示问题详细信息时再启用
debug: false
# 节点uuid，第一次使用时会随机生成，请勿更改
uuid: '''+str(uuid.uuid4())
        file.write(data)
    logging.info('配置文件已生成，路径为'+config_path+'，请修改其中的配置后再次运行程序')
    time.sleep(3)
    sys.exit()
logger = logging.getLogger()
if node_debug:
    logger.setLevel(logging.DEBUG)
else:
    logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(ColoredFormatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.handlers.clear()
logger.addHandler(handler)
server_key = "h8WQ0NiQHPSOIDL8YgsohndEBfEuuRqt"
server_iv = "A3NyHTbzQEhrZHqc"
qrcode_sign_list = {}
bytesend = bytearray([0x1A, 0x16, 0x63, 0x6F, 0x6E, 0x66, 0x65, 0x72, 0x65, 0x6E, 0x63, 0x65, 0x2E, 0x65, 0x61, 0x73, 0x65, 0x6D, 0x6F, 0x62, 0x2E, 0x63, 0x6F, 0x6D])
BytesAttachment = bytearray([0x0a, 0x61, 0x74, 0x74, 0x61, 0x63, 0x68, 0x6D, 0x65, 0x6E, 0x74, 0x10, 0x08, 0x32])
chaoxing_headers = {
    'Accept-Encoding': 'gzip, deflate',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
    'User-Agent': 'Mozilla/5.0 (Linux; Android 12; Redmi K30 Pro Zoom Edition Build/SKQ1.211006.001; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/95.0.4638.74 Mobile Safari/537.36 (device:Redmi K30 Pro Zoom Edition) Language/zh_CN com.chaoxing.mobile/ChaoXingStudy_3_5.2.6_android_phone_856_81 (@Kalimdor)_8c0587fc07ee4c25bdbbb5d7a90d8152'
}
browser_headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36"
}
version = "1.0"
user_list = {}


async def send_email(text, user_email, result):
    try:
        if email_address != "":
            msg = MIMEText(text, 'html', 'utf-8')
            msg['From'] = formataddr((email_user, email_address))
            msg['To'] = formataddr(("", user_email))
            msg['Subject'] = result
            server = aiosmtplib.SMTP(hostname=email_host, port=email_port, use_tls=email_use_tls)
            await server.connect()
            await server.login(email_address, email_password)
            await server.sendmail(email_address, user_email, msg.as_string())
            await server.quit()
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def stop_reason(num, uid, name, email):
    try:
        if num == 1:
            reason = '学习通账号登录失败'
        elif num == 2:
            reason = '课程和班级列表获取失败'
        elif num == 3:
            reason = '全部签到接口均失效'
        else:
            reason = '未知原因'
        logging.info(name+"：由于"+reason+"停止签到")
        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"签到异常停止，停止原因为"+reason+"\n"}), server_key, server_iv)
        await send_message(sign_server_ws, encrypt)
        asyncio.create_task(send_email("<p>【学习通在线自动签到系统监控异常停止通知】</p><p style=\"text-indent:2em;\">您的签到监控异常停止，停止原因为“"+reason+"”，请您登录学习通在线自动签到系统查看详情。</p>", email, "学习通在线自动签到系统监控异常停止通知"))
        asyncio.create_task(send_wechat_message(uid, "【学习通在线自动签到系统监控异常停止通知】 您的签到监控异常停止，停止原因为“"+reason+"”，请您登录学习通在线自动签到系统查看详情"))
        await remove_sign_info(uid)
        if num != 3:
            encrypt = await get_data_aes_encode(json.dumps({"type": "user_logout", "uid": uid, "name": name}), server_key, server_iv)
            await send_message(sign_server_ws, encrypt)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def interface_two(session, uid, name, courseid, classid, username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, na, address, longitude, latitude, objectid, email):
    try:
        if user_list[uid]["port"] == 2:
            url = "https://mobilelearn.chaoxing.com/ppt/activeAPI/taskactivelist?courseId="+str(courseid)+"&classId="+str(classid)+"&uid="+str(uid)
            while True:
                try:
                    async with session.get(url, headers=chaoxing_headers, timeout=10) as resp:
                        res = json.loads(await resp.text())
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            if res['result']:
                user_list[uid]["error_num"] = 0
                for i in range(len(res['activeList'])):
                    if res['activeList'][i]['activeType'] == 2 and res['activeList'][i]['status'] == 1 and res['activeList'][i]["startTime"]/1000+86400 > int(time.time()):
                        aid = res['activeList'][i]['id']
                        if str(aid) not in user_list[uid]["signed_in_list"]:
                            user_list[uid]["sign_task_list"][str(aid)] = asyncio.create_task(signt(session, uid, name, courseid, classid, aid, username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, res['activeList'][i]['nameOne'], na, address, longitude, latitude, objectid, email))
            elif res['errorMsg'] == "请登录后再试":
                asyncio.create_task(stop_reason(1, uid, name, email))
                return 1
            else:
                if user_list[uid]["error_num"] < 3:
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"在使用接口2（APP端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+res["errorMsg"]+"”，系统将尝试使用接口3（网页端接口）进行签到监控\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到接口切换通知】</p><p style=\"text-indent:2em;\">在使用接口2（APP端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+res["errorMsg"]+"”，系统将尝试使用接口3（网页端接口）进行签到监控。</p>", email, "学习通在线自动签到系统签到接口切换通知"))
                    asyncio.create_task(send_wechat_message(uid, "【学习通在线自动签到系统签到接口切换通知】 在使用接口2（APP端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+res["errorMsg"]+"”，系统将尝试使用接口3（网页端接口）进行签到监控"))
                    user_list[uid]["port"] = 3
                    encrypt = await get_data_aes_encode(json.dumps({"type": "change_port", "uid": str(uid), "name": name, "port": 3}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    user_list[uid]["error_num"] += 1
                    return await interface_three(session, uid, name, courseid, classid, username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, na, address, longitude, latitude, objectid, email)
                else:
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"在使用接口2（APP端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+res["errorMsg"]+"”，接口2、接口3和接口4均被封禁，请尝试使用接口1（IM协议实时接口）进行签到监控或等待一小时后再尝试使用接口2、接口3和接口4进行签到监控\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    asyncio.create_task(send_email("<p>【学习通在线自动签到系统停止监控通知】</p><p style=\"text-indent:2em;\">在使用接口2（APP端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+res["errorMsg"]+"”，接口2、接口3和接口4均被封禁，请尝试使用接口1（IM协议实时接口）进行签到监控或等待一小时后再尝试使用接口2、接口3和接口4进行签到监控。</p>", email, "学习通在线自动签到系统停止监控通知"))
                    asyncio.create_task(send_wechat_message(uid, "【学习通在线自动签到系统停止监控通知】 在使用接口2（APP端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+res["errorMsg"]+"”，接口2、接口3和接口4均被封禁，请尝试使用接口1（IM协议实时接口）进行签到监控或等待一小时后再尝试使用接口2、接口3和接口4进行签到监控"))
                    user_list[uid]["error_num"] = 0
                    asyncio.create_task(stop_reason(3, uid, name, email))
                    return 1
        elif user_list[uid]["port"] == 3:
            return await interface_three(session, uid, name, courseid, classid, username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, na, address, longitude, latitude, objectid, email)
        elif user_list[uid]["port"] == 4:
            return await interface_four(session, uid, name, courseid, classid, username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, na, address, longitude, latitude, objectid, email)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def interface_three(session, uid, name, courseid, classid, username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, na, address, longitude, latitude, objectid, email):
    try:
        if user_list[uid]["port"] == 3:
            if str(user_list[uid]["schoolid"]) == "":
                fid = "0"
            else:
                fid = str(user_list[uid]["schoolid"])
            url = "https://mobilelearn.chaoxing.com/v2/apis/active/student/activelist?fid="+fid+"&courseId="+str(courseid)+"&classId="+str(classid)
            while True:
                try:
                    async with session.get(url, headers=chaoxing_headers, timeout=10) as resp:
                        if str(resp.url) == url:
                            res = json.loads(await resp.text())
                        else:
                            asyncio.create_task(stop_reason(1, uid, name, email))
                            return 1
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            if res['result']:
                user_list[uid]["error_num"] = 0
                for _data in res['data']['activeList']:
                    if _data['activeType'] == 2 and _data['status'] == 1 and _data["startTime"]/1000+86400 > int(time.time()):
                        aid = _data['id']
                        if str(aid) not in user_list[uid]["signed_in_list"]:
                            user_list[uid]["sign_task_list"][str(aid)] = asyncio.create_task(signt(session, uid, name, courseid, classid, aid, username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, _data['nameOne'], na, address, longitude, latitude, objectid, email))
            else:
                if user_list[uid]["error_num"] < 3:
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"在使用接口3（网页端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+res["errorMsg"]+"”，系统将尝试使用接口4（教师端接口）进行签到监控\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到接口切换通知】</p><p style=\"text-indent:2em;\">在使用接口3（网页端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+res["errorMsg"]+"”，系统将尝试使用接口4（教师端接口）进行签到监控。</p>", email, "学习通在线自动签到系统签到接口切换通知"))
                    asyncio.create_task(send_wechat_message(uid, "【学习通在线自动签到系统签到接口切换通知】 在使用接口3（网页端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+res["errorMsg"]+"”，系统将尝试使用接口4（教师端接口）进行签到监控"))
                    user_list[uid]["port"] = 4
                    encrypt = await get_data_aes_encode(json.dumps({"type": "change_port", "uid": str(uid), "name": name, "port": 4}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    user_list[uid]["error_num"] += 1
                    return await interface_four(session, uid, name, courseid, classid, username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, na, address, longitude, latitude, objectid, email)
                else:
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"在使用接口3（网页端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+res["errorMsg"]+"”，接口2、接口3和接口4均被封禁，请尝试使用接口1（IM协议实时接口）进行签到监控或等待一小时后再尝试使用接口2、接口3和接口4进行签到监控\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    asyncio.create_task(send_email("<p>【学习通在线自动签到系统停止监控通知】</p><p style=\"text-indent:2em;\">在使用接口3（网页端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+res["errorMsg"]+"”，接口2、接口3和接口4均被封禁，请尝试使用接口1（IM协议实时接口）进行签到监控或等待一小时后再尝试使用接口2、接口3和接口4进行签到监控。</p>", email, "学习通在线自动签到系统停止监控通知"))
                    asyncio.create_task(send_wechat_message(uid, "【学习通在线自动签到系统停止监控通知】 在使用接口3（网页端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+res["errorMsg"]+"”，接口2、接口3和接口4均被封禁，请尝试使用接口1（IM协议实时接口）进行签到监控或等待一小时后再尝试使用接口2、接口3和接口4进行签到监控"))
                    user_list[uid]["error_num"] = 0
                    asyncio.create_task(stop_reason(3, uid, name, email))
                    return 1
        elif user_list[uid]["port"] == 2:
            return await interface_two(session, uid, name, courseid, classid, username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, na, address, longitude, latitude, objectid, email)
        elif user_list[uid]["port"] == 4:
            return await interface_four(session, uid, name, courseid, classid, username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, na, address, longitude, latitude, objectid, email)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def interface_four(session, uid, name, courseid, classid, username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, na, address, longitude, latitude, objectid, email):
    try:
        if user_list[uid]["port"] == 4:
            url = "https://mobilelearn.chaoxing.com/widget/activeDisplay/getTeacherActiveListV3Data?DB_STRATEGY=COURSEID&STRATEGY_PARA=courseId&classId="+str(classid)+"&courseId="+str(courseid)+"&t="+str(int(time.time()*1000))
            while True:
                try:
                    async with session.get(url, headers=chaoxing_headers, timeout=10) as resp:
                        if resp.status == 502:
                            continue
                        elif url != str(resp.url):
                            asyncio.create_task(stop_reason(1, uid, name, email))
                            return 1
                        res = json.loads(await resp.text())
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            if res['result']:
                user_list[uid]["error_num"] = 0
                for _data in res['data']['activeListData']:
                    if _data['activeType'] == 2 and _data['status'] == "1":
                        aid = str(_data['aid'])
                        if aid not in user_list[uid]["signed_in_list"]:
                            panduanurl = 'https://mobilelearn.chaoxing.com/v2/apis/active/getPPTActiveInfo?activeId='+str(aid)+'&duid=&denc='
                            con_flag = False
                            while True:
                                try:
                                    async with session.get(panduanurl, headers=chaoxing_headers, timeout=10) as resp:
                                        res = json.loads(await resp.text())
                                    if not res["result"]:
                                        asyncio.create_task(stop_reason(1, uid, name, email))
                                        return 1
                                    elif res["data"]["starttime"]//1000+86400 < int(time.time()):
                                        user_list[uid]["signed_in_list"].append(str(aid))
                                        con_flag = True
                                    break
                                except Exception as e:
                                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                            if not con_flag:
                                user_list[uid]["sign_task_list"][str(aid)] = asyncio.create_task(signt(session, uid, name, courseid, classid, aid, username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, _data['title'], na, address, longitude, latitude, objectid, email))
                            else:
                                continue
            else:
                if user_list[uid]["error_num"] < 3:
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"在使用接口4（教师端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+res["errorMsg"]+"”，系统将尝试使用接口2（APP端接口）进行签到监控\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到接口切换通知】</p><p style=\"text-indent:2em;\">在使用接口4（教师端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+res["errorMsg"]+"”，系统将尝试使用接口2（APP端接口）进行签到监控。</p>", email, "学习通在线自动签到系统签到接口切换通知"))
                    asyncio.create_task(send_wechat_message(uid, "【学习通在线自动签到系统签到接口切换通知】 在使用接口4（教师端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+res["errorMsg"]+"”，系统将尝试使用接口2（APP端接口）进行签到监控"))
                    user_list[uid]["port"] = 2
                    encrypt = await get_data_aes_encode(json.dumps({"type": "change_port", "uid": str(uid), "name": name, "port": 2}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    user_list[uid]["error_num"] += 1
                    return await interface_two(session, uid, name, courseid, classid, username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, na, address, longitude, latitude, objectid, email)
                else:
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"在使用接口4（教师端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+res["errorMsg"]+"”，接口2、接口3和接口4均被封禁，请尝试使用接口1（IM协议实时接口）进行签到监控或等待一小时后再尝试使用接口2、接口3和接口4进行签到监控\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    asyncio.create_task(send_email("<p>【学习通在线自动签到系统停止监控通知】</p><p style=\"text-indent:2em;\">在使用接口4（教师端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+res["errorMsg"]+"”，接口2、接口3和接口4均被封禁，请尝试使用接口1（IM协议实时接口）进行签到监控或等待一小时后再尝试使用接口2、接口3和接口4进行签到监控。</p>", email, "学习通在线自动签到系统停止监控通知"))
                    asyncio.create_task(send_wechat_message(uid, "【学习通在线自动签到系统停止监控通知】 在使用接口4（教师端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+res["errorMsg"]+"”，接口2、接口3和接口4均被封禁，请尝试使用接口1（IM协议实时接口）进行签到监控或等待一小时后再尝试使用接口2、接口3和接口4进行签到监控"))
                    user_list[uid]["error_num"] = 0
                    asyncio.create_task(stop_reason(3, uid, name, email))
                    return 1
        elif user_list[uid]["port"] == 2:
            return await interface_two(session, uid, name, courseid, classid, username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, na, address, longitude, latitude, objectid, email)
        elif user_list[uid]["port"] == 3:
            return await interface_three(session, uid, name, courseid, classid, username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, na, address, longitude, latitude, objectid, email)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def signt(session, uid, name, course_id, class_id, aid, username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, name_one, na, address, longitude, latitude, objectid, email):
    try:
        user_list[uid]["signed_in_list"].append(str(aid))
        if user_list[uid]["port"] != 1:
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"课程或班级“"+na+"”监测到签到活动，签到活动名称为“"+name_one+"”\n"}), server_key, server_iv)
            await send_message(sign_server_ws, encrypt)
        panduanurl = 'https://mobilelearn.chaoxing.com/v2/apis/active/getPPTActiveInfo?activeId='+str(aid)+'&duid=&denc='
        while True:
            try:
                async with session.get(panduanurl, headers=chaoxing_headers, timeout=10) as resp:
                    res = json.loads(await resp.text())
                    if "multiClassesActives" in res['data'].keys():
                        _aid = res['data']["multiClassesActives"][0]["aid"]
                        _class_id = res['data']["multiClassesActives"][0]["cid"]
                    else:
                        _aid = aid
                        _class_id = class_id
                if not res["result"]:
                    asyncio.create_task(stop_reason(1, uid, name, email))
                    return 1
                break
            except Exception as e:
                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
        if res['data']['otherId'] == 2:
            set_address = ""
            set_longitude = -1
            set_latitude = -1
            if res['data']['ifrefreshewm'] == 1 and res['data']['ifopenAddress'] == 1:
                get_locationurl = 'https://mobilelearn.chaoxing.com/v2/apis/sign/getLocationLog?DB_STRATEGY=COURSEID&STRATEGY_PARA=courseId&courseId='+str(course_id)+'&classId='+str(_class_id)
                while True:
                    try:
                        async with session.get(get_locationurl, headers=chaoxing_headers, timeout=10) as resp:
                            rres = json.loads(await resp.text())
                        break
                    except Exception as e:
                        logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                if rres["result"]:
                    is_find = False
                    for d in rres["data"]:
                        if str(d["activeid"]) == str(_aid):
                            set_address = str(d["address"])
                            set_longitude = str(d["longitude"])
                            set_latitude = str(d["latitude"])
                            is_find = True
                            break
                    if is_find:
                        send_text = "，签到活动名称为“"+name_one+"”，指定签到地点为“"+set_address+"”，请使用微信小程序“WAADRI的扫码工具”扫描学习通签到二维码来完成自动签到。"
                        send_text2 = "，指定签到地点为“"+set_address+"”，请使用微信小程序“WAADRI的扫码工具”扫描学习通签到二维码来完成自动签到"
                        send_text3 = "，指定签到地点为“"+set_address+"”"
                    else:
                        get_locationurl = "https://mobilelearn.chaoxing.com/pptSign/errorLocation?DB_STRATEGY=PRIMARY_KEY&STRATEGY_PARA=activeId&activeId="+str(aid)+"&uid="+str(uid)+"&location=%7B%22result%22%3A%201%2C%20%22latitude%22%3A%2039.5426%2C%20%22longitude%22%3A%20116.2329%2C%20%22address%22%3A%20%22%E4%B8%AD%E5%9B%BD%E5%8C%97%E4%BA%AC%E5%B8%82%22%7D&errortype=errorLocation2"
                        while True:
                            try:
                                async with session.get(get_locationurl, headers=chaoxing_headers, timeout=10) as resp:
                                    rres_text = await resp.text()
                                break
                            except Exception as e:
                                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                        if re.search(r'<input type="hidden" id="locationText" value="(.+)">', rres_text, re.I) is not None:
                            set_address = re.search(r'<input type="hidden" id="locationText" value="(.+)">', rres_text, re.I).groups()[0]
                            set_latitude = re.search(r'<input type="hidden" id="locationLatitude" value="(.+)">', rres_text, re.I).groups()[0]
                            set_longitude = re.search(r'<input type="hidden" id="locationLongitude" value="(.+)">', rres_text, re.I).groups()[0]
                            send_text = "，签到活动名称为“"+name_one+"”，指定签到地点为“"+set_address+"”，请使用微信小程序“WAADRI的扫码工具”扫描学习通签到二维码来完成自动签到。"
                            send_text2 = "，指定签到地点为“"+set_address+"”，请使用微信小程序“WAADRI的扫码工具”扫描学习通签到二维码来完成自动签到"
                            send_text3 = "，指定签到地点为“"+set_address+"”"
                        else:
                            send_text = "，签到活动名称为“"+name_one+"”，但无法获取指定位置信息，请使用微信小程序“WAADRI的扫码工具”选择指定位置并扫描学习通签到二维码来完成自动签到。"
                            send_text2 = "，但无法获取指定位置信息，请使用微信小程序“WAADRI的扫码工具”选择指定位置并扫描学习通签到二维码来完成自动签到"
                            send_text3 = "，但无法获取指定位置信息"
                else:
                    send_text = "，签到活动名称为“"+name_one+"”，但无法获取指定位置信息，请使用微信小程序“WAADRI的扫码工具”选择指定位置并扫描学习通签到二维码来完成自动签到。"
                    send_text2 = "，但无法获取指定位置信息，请使用微信小程序“WAADRI的扫码工具”选择指定位置并扫描学习通签到二维码来完成自动签到"
                    send_text3 = "，但无法获取指定位置信息"
                asyncio.create_task(send_email("<p>【学习通在线自动签到系统二维码签到扫码通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到"+str(res['data']['ewmRefreshTime'])+"秒自动更新且指定了签到地点的二维码签到"+send_text+"<a href=\"https://api.waadri.top/ChaoXing/MSIT.php\">小程序使用教程点这里</a>。</p><p style=\"text-indent:2em;\">微信小程序二维码：</p><img src=\"https://www.waadri.top/source/gh_3c371f2be720_1280.jpg\" style=\"width: 100%;height: auto;max-width: 200px;max-height: auto;\">", email, "学习通二维码签到扫码通知"))
                asyncio.create_task(send_wechat_message(uid, "【学习通二维码签到扫码通知】 课程或班级“"+na+"”监测到"+str(res['data']['ewmRefreshTime'])+"秒自动更新且指定了签到地点的二维码签到"+send_text+"小程序使用教程见https://api.waadri.top/ChaoXing/MSIT.php"))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为"+str(res['data']['ewmRefreshTime'])+"秒自动更新且指定了签到地点的二维码签到"+send_text2+"，小程序使用教程见https://api.waadri.top/ChaoXing/MSIT.php\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
            elif res['data']['ifrefreshewm'] == 1:
                asyncio.create_task(send_email("<p>【学习通在线自动签到系统二维码签到扫码通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到"+str(res['data']['ewmRefreshTime'])+"秒自动更新且未指定签到地点的二维码签到，签到活动名称为“"+name_one+"”，请使用微信小程序“WAADRI的扫码工具”扫描学习通签到二维码来完成自动签到。<a href=\"https://api.waadri.top/ChaoXing/MSIT.php\">小程序使用教程点这里</a>。</p><p style=\"text-indent:2em;\">微信小程序二维码：</p><img src=\"https://www.waadri.top/source/gh_3c371f2be720_1280.jpg\" style=\"width: 100%;height: auto;max-width: 200px;max-height: auto;\">", email, "学习通二维码签到扫码通知"))
                asyncio.create_task(send_wechat_message(uid, "【学习通二维码签到扫码通知】 课程或班级“"+na+"”监测到"+str(res['data']['ewmRefreshTime'])+"秒自动更新且未指定签到地点的二维码签到，签到活动名称为“"+name_one+"”，请使用微信小程序“WAADRI的扫码工具”扫描学习通签到二维码来完成自动签到。小程序使用教程见https://api.waadri.top/ChaoXing/MSIT.php"))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为"+str(res['data']['ewmRefreshTime'])+"秒自动更新且未指定签到地点的二维码签到，请使用微信小程序“WAADRI的扫码工具”扫描学习通签到二维码来完成自动签到，小程序使用教程见https://api.waadri.top/ChaoXing/MSIT.php\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
            elif res['data']['ifopenAddress'] == 1:
                get_locationurl = 'https://mobilelearn.chaoxing.com/v2/apis/sign/getLocationLog?DB_STRATEGY=COURSEID&STRATEGY_PARA=courseId&courseId='+str(course_id)+'&classId='+str(_class_id)
                while True:
                    try:
                        async with session.get(get_locationurl, headers=chaoxing_headers, timeout=10) as resp:
                            rres = json.loads(await resp.text())
                        break
                    except Exception as e:
                        logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                if rres["result"]:
                    is_find = False
                    for d in rres["data"]:
                        if str(d["activeid"]) == str(_aid):
                            set_address = str(d["address"])
                            set_longitude = str(d["longitude"])
                            set_latitude = str(d["latitude"])
                            is_find = True
                            break
                    if is_find:
                        send_text = "，签到活动名称为“"+name_one+"”，指定签到地点为“"+set_address+"”，请使用微信小程序“WAADRI的扫码工具”扫描学习通签到二维码来完成自动签到。"
                        send_text2 = "，指定签到地点为“"+set_address+"”，请使用微信小程序“WAADRI的扫码工具”扫描学习通签到二维码来完成自动签到"
                        send_text3 = "，指定签到地点为“"+set_address+"”"
                    else:
                        get_locationurl = "https://mobilelearn.chaoxing.com/pptSign/errorLocation?DB_STRATEGY=PRIMARY_KEY&STRATEGY_PARA=activeId&activeId="+str(aid)+"&uid="+str(uid)+"&location=%7B%22result%22%3A%201%2C%20%22latitude%22%3A%2039.5426%2C%20%22longitude%22%3A%20116.2329%2C%20%22address%22%3A%20%22%E4%B8%AD%E5%9B%BD%E5%8C%97%E4%BA%AC%E5%B8%82%22%7D&errortype=errorLocation2"
                        while True:
                            try:
                                async with session.get(get_locationurl, headers=chaoxing_headers, timeout=10) as resp:
                                    rres_text = await resp.text()
                                break
                            except Exception as e:
                                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                        if re.search(r'<input type="hidden" id="locationText" value="(.+)">', rres_text, re.I) is not None:
                            set_address = re.search(r'<input type="hidden" id="locationText" value="(.+)">', rres_text, re.I).groups()[0]
                            set_latitude = re.search(r'<input type="hidden" id="locationLatitude" value="(.+)">', rres_text, re.I).groups()[0]
                            set_longitude = re.search(r'<input type="hidden" id="locationLongitude" value="(.+)">', rres_text, re.I).groups()[0]
                            send_text = "，签到活动名称为“"+name_one+"”，指定签到地点为“"+set_address+"”，请使用微信小程序“WAADRI的扫码工具”扫描学习通签到二维码来完成自动签到。"
                            send_text2 = "，指定签到地点为“"+set_address+"”，请使用微信小程序“WAADRI的扫码工具”扫描学习通签到二维码来完成自动签到"
                            send_text3 = "，指定签到地点为“"+set_address+"”"
                        else:
                            send_text = "，签到活动名称为“"+name_one+"”，但无法获取指定位置信息，请使用微信小程序“WAADRI的扫码工具”选择指定位置并扫描学习通签到二维码来完成自动签到。"
                            send_text2 = "，但无法获取指定位置信息，请使用微信小程序“WAADRI的扫码工具”选择指定位置并扫描学习通签到二维码来完成自动签到"
                            send_text3 = "，但无法获取指定位置信息"
                else:
                    send_text = "，签到活动名称为“"+name_one+"”，但无法获取指定位置信息，请使用微信小程序“WAADRI的扫码工具”选择指定位置并扫描学习通签到二维码来完成自动签到。"
                    send_text2 = "，但无法获取指定位置信息，请使用微信小程序“WAADRI的扫码工具”选择指定位置并扫描学习通签到二维码来完成自动签到"
                    send_text3 = "，但无法获取指定位置信息"
                asyncio.create_task(send_email("<p>【学习通在线自动签到系统二维码签到扫码通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到无自动更新且指定了签到地点的二维码签到"+send_text+"<a href=\"https://api.waadri.top/ChaoXing/MSIT.php\">小程序使用教程点这里</a>。</p><p style=\"text-indent:2em;\">微信小程序二维码：</p><img src=\"https://www.waadri.top/source/gh_3c371f2be720_1280.jpg\" style=\"width: 100%;height: auto;max-width: 200px;max-height: auto;\">", email, "学习通二维码签到扫码通知"))
                asyncio.create_task(send_wechat_message(uid, "【学习通二维码签到扫码通知】 课程或班级“"+na+"”监测到无自动更新且指定了签到地点的二维码签到"+send_text+"小程序使用教程见https://api.waadri.top/ChaoXing/MSIT.php"))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为无自动更新且指定了签到地点的二维码签到"+send_text2+"，小程序使用教程见https://api.waadri.top/ChaoXing/MSIT.php\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
            else:
                asyncio.create_task(send_email("<p>【学习通在线自动签到系统二维码签到扫码通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到无自动更新且未指定签到地点的二维码签到，签到活动名称为“"+name_one+"”，请使用微信小程序“WAADRI的扫码工具”扫描学习通签到二维码来完成自动签到。<a href=\"https://api.waadri.top/ChaoXing/MSIT.php\">小程序使用教程点这里</a>。</p><p style=\"text-indent:2em;\">微信小程序二维码：</p><img src=\"https://www.waadri.top/source/gh_3c371f2be720_1280.jpg\" style=\"width: 100%;height: auto;max-width: 200px;max-height: auto;\">", email, "学习通二维码签到扫码通知"))
                asyncio.create_task(send_wechat_message(uid, "【学习通二维码签到扫码通知】 课程或班级“"+na+"”监测到无自动更新且未指定签到地点的二维码签到，签到活动名称为“"+name_one+"”，请使用微信小程序“WAADRI的扫码工具”扫描学习通签到二维码来完成自动签到。小程序使用教程见https://api.waadri.top/ChaoXing/MSIT.php"))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为无自动更新且未指定签到地点的二维码签到，请使用微信小程序“WAADRI的扫码工具”扫描学习通签到二维码来完成自动签到，小程序使用教程见https://api.waadri.top/ChaoXing/MSIT.php\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
            temp_data = {"session": session, "name": user_list[uid]["name"], "courseid": course_id, "classid": class_id, "aid": str(aid), "_aid": str(_aid), "uid": uid, "lesson_name": na, "username": username, "password": password, "schoolid": schoolid, "cookie": cookie, "is_numing": is_numing, "sign_num": sign_num, "address": set_address, "longitude": set_longitude, "latitude": set_latitude, "email": email}
            qrcode_sign_list[str(uid)+str(aid)] = temp_data
            _data = {"type": "get_qrcode", "qrcode_sign_list": [str(_aid)]}
            _data = await get_data_aes_encode(json.dumps(_data), server_key, server_iv)
            await send_message(sign_server_ws, _data)
            del user_list[uid]["sign_task_list"][str(aid)]
        else:
            url = "https://mobilelearn.chaoxing.com/pptSign/stuSignajax"
            append_text = ""
            if res['data']['otherId'] == 0:
                if res['data']['ifphoto'] == 1:
                    if is_anti_fishing and is_embezzle and (info_type == "all" or info_type == "picture"):
                        while True:
                            try:
                                async with session.get("https://mobilelearn.chaoxing.com/widget/sign/pcTeaSignController/getAttendList?activeId="+str(aid)+"&appType=15&classId="+str(class_id)+"&fid=0", headers=browser_headers, timeout=10) as resp:
                                    res1 = json.loads(await resp.text())
                                break
                            except Exception as e:
                                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                        student_count = res1["data"]["weiqian"]+res1["data"]["yiqian"]
                        asyncio.create_task(send_email("<p>【学习通在线自动签到系统拍照签到通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到拍照签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统将在监测到已签人数不少于未签人数后随机使用其他已签到同学的拍照图片进行自动签到。</p>", email, "学习通拍照签到通知"))
                        asyncio.create_task(send_wechat_message(uid, "【学习通拍照签到通知】 课程或班级“"+na+"”监测到拍照签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统将在监测到已签人数不少于未签人数后随机使用其他已签到同学的拍照图片进行自动签到"))
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为拍照签到，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统将在监测到已签人数不少于未签人数后随机使用其他已签到同学的拍照图片进行自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                        while True:
                            result = await anti_fishing_check_in_mode(student_count, session, aid)
                            if result is None:
                                asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到人数取消监控通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到拍照签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控。</p>", email, "学习通签到人数取消监控通知"))
                                asyncio.create_task(send_wechat_message(uid, "【学习通签到人数取消监控通知】 课程或班级“"+na+"”监测到拍照签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控"))
                                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为拍照签到，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控\n"}), server_key, server_iv)
                                await send_message(sign_server_ws, encrypt)
                                del user_list[uid]["sign_task_list"][str(aid)]
                                return
                            elif result:
                                break
                            else:
                                await asyncio.sleep(2)
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"监测到已签人数已不少于未签人数，开始自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                        result = await monitor_the_sign_in_of_other_students(session, "photo", aid, class_id)
                        if result is None:
                            asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到取消通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到拍照签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统在盗用签到信息时发现签到已过期或签到发布时长超过24小时，因此取消对当前签到活动进行签到。</p>", email, "学习通签到取消通知"))
                            asyncio.create_task(send_wechat_message(uid, "【学习通签到取消通知】 课程或班级“"+na+"”监测到拍照签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统在盗用签到信息时发现签到已过期或签到发布时长超过24小时，因此取消对当前签到活动进行签到"))
                            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为拍照签到，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统在盗用签到信息时发现签到已过期或签到发布时长超过24小时，因此取消对当前签到活动进行签到\n"}), server_key, server_iv)
                            await send_message(sign_server_ws, encrypt)
                            del user_list[uid]["sign_task_list"][str(aid)]
                            return
                        else:
                            use_name = result[0]
                            objectid = result[1]
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"随机使用"+use_name+"同学的拍照图片进行自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                        append_text = "，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统随机使用"+use_name+"同学的拍照图片进行签到"
                    elif is_anti_fishing:
                        while True:
                            try:
                                async with session.get("https://mobilelearn.chaoxing.com/widget/sign/pcTeaSignController/getAttendList?activeId="+str(aid)+"&appType=15&classId="+str(class_id)+"&fid=0", headers=browser_headers, timeout=10) as resp:
                                    res1 = json.loads(await resp.text())
                                break
                            except Exception as e:
                                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                        student_count = res1["data"]["weiqian"]+res1["data"]["yiqian"]
                        asyncio.create_task(send_email("<p>【学习通在线自动签到系统拍照签到通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到拍照签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到。</p>", email, "学习通拍照签到通知"))
                        asyncio.create_task(send_wechat_message(uid, "【学习通拍照签到通知】 课程或班级“"+na+"”监测到拍照签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到"))
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为拍照签到，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                        while True:
                            result = await anti_fishing_check_in_mode(student_count, session, aid)
                            if result is None:
                                asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到人数取消监控通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到拍照签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控。</p>", email, "学习通签到人数取消监控通知"))
                                asyncio.create_task(send_wechat_message(uid, "【学习通签到人数取消监控通知】 课程或班级“"+na+"”监测到拍照签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控"))
                                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为拍照签到，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控\n"}), server_key, server_iv)
                                await send_message(sign_server_ws, encrypt)
                                del user_list[uid]["sign_task_list"][str(aid)]
                                return
                            elif result:
                                break
                            else:
                                await asyncio.sleep(2)
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"监测到已签人数已不少于未签人数，开始自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                    elif is_embezzle and (info_type == "all" or info_type == "picture"):
                        asyncio.create_task(send_email("<p>【学习通在线自动签到系统拍照签到通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到拍照签到，签到活动名称为“"+name_one+"”，由于您启用了签到信息盗用模式，系统将在其他同学签到后随机使用其他已签到同学的拍照图片进行自动签到。</p>", email, "学习通拍照签到通知"))
                        asyncio.create_task(send_wechat_message(uid, "【学习通拍照签到通知】 课程或班级“"+na+"”监测到拍照签到，签到活动名称为“"+name_one+"”，由于您启用了签到信息盗用模式，系统将在其他同学签到后随机使用其他已签到同学的拍照图片进行自动签到"))
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为拍照签到，由于您启用了签到信息盗用模式，系统将在其他同学签到后随机使用其他已签到同学的拍照图片进行自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                        result = await monitor_the_sign_in_of_other_students(session, "photo", aid, class_id)
                        if result is None:
                            asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到取消通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到拍照签到，签到活动名称为“"+name_one+"”，由于您启用了签到信息盗用模式，系统在盗用签到信息时发现签到已过期或签到发布时长超过24小时，因此取消对当前签到活动进行签到。</p>", email, "学习通签到取消通知"))
                            asyncio.create_task(send_wechat_message(uid, "【学习通签到取消通知】 课程或班级“"+na+"”监测到拍照签到，签到活动名称为“"+name_one+"”，由于您启用了签到信息盗用模式，系统在盗用签到信息时发现签到已过期或签到发布时长超过24小时，因此取消对当前签到活动进行签到"))
                            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为拍照签到，由于您启用了签到信息盗用模式，系统在盗用签到信息时发现签到已过期或签到发布时长超过24小时，因此取消对当前签到活动进行签到\n"}), server_key, server_iv)
                            await send_message(sign_server_ws, encrypt)
                            del user_list[uid]["sign_task_list"][str(aid)]
                            return
                        else:
                            use_name = result[0]
                            objectid = result[1]
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"随机使用"+use_name+"同学的拍照图片进行自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                        append_text = "，由于您启用了签到信息盗用模式，系统随机使用"+use_name+"同学的拍照图片进行签到"
                    elif objectid == "":
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为拍照签到，但您未设置拍照图片，将使用普通签到模式执行无拍照图片自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                        append_text = "，由于您未设置拍照图片，因此使用普通签到模式执行无拍照图片自动签到"
                    else:
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为拍照签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                    sign_type = sign_type2 = "拍照签到"
                    _data = {
                        'name': user_list[uid]["name"],
                        'activeId': aid,
                        'uid': uid,
                        'objectId': objectid
                    }
                else:
                    if is_anti_fishing:
                        while True:
                            try:
                                async with session.get("https://mobilelearn.chaoxing.com/widget/sign/pcTeaSignController/getAttendList?activeId="+str(aid)+"&appType=15&classId="+str(class_id)+"&fid=0", headers=browser_headers, timeout=10) as resp:
                                    res1 = json.loads(await resp.text())
                                break
                            except Exception as e:
                                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                        student_count = res1["data"]["weiqian"]+res1["data"]["yiqian"]
                        asyncio.create_task(send_email("<p>【学习通在线自动签到系统普通签到通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到普通签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到。</p>", email, "学习通普通签到通知"))
                        asyncio.create_task(send_wechat_message(uid, "【学习通普通签到通知】 课程或班级“"+na+"”监测到普通签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到"))
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为普通签到，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                        while True:
                            result = await anti_fishing_check_in_mode(student_count, session, aid)
                            if result is None:
                                asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到人数取消监控通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到普通签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控。</p>", email, "学习通签到人数取消监控通知"))
                                asyncio.create_task(send_wechat_message(uid, "【学习通签到人数取消监控通知】 课程或班级“"+na+"”监测到普通签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控"))
                                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为普通签到，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控\n"}), server_key, server_iv)
                                await send_message(sign_server_ws, encrypt)
                                del user_list[uid]["sign_task_list"][str(aid)]
                                return
                            elif result:
                                break
                            else:
                                await asyncio.sleep(2)
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"监测到已签人数已不少于未签人数，开始自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                    else:
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为普通签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                    sign_type = sign_type2 = "普通签到"
                    _data = {
                        'name': user_list[uid]["name"],
                        'activeId': aid,
                        'uid': uid,
                    }
            elif res['data']['otherId'] == 3:
                while True:
                    try:
                        async with session.get("https://mobilelearn.chaoxing.com/widget/sign/pcTeaSignController/endSign?activeId="+str(aid)+"&classId="+str(class_id)+"&fid=&courseId="+str(course_id)+"&isTeacherViewOpen=1", headers=chaoxing_headers, timeout=10) as resp:
                            rres = await resp.text()
                        break
                    except Exception as e:
                        logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                check_sign_code = re.search(r'<input type="hidden" id="signCode" value="(\d+)" />', rres, re.I)
                if check_sign_code is None:
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为手势签到，但无法获取签到手势\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到失败通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到手势签到，签到活动名称为“"+name_one+append_text+"”，但在线签到系统未能成功完成自动签到，失败原因为“无法获取签到手势”。</p>", email, "学习通手势签到结果：签到失败"))
                    asyncio.create_task(send_wechat_message(uid, "【学习通手势签到结果：签到失败】 课程或班级“"+na+"”监测到手势签到，签到活动名称为“"+name_one+append_text+"”，但在线签到系统未能成功完成自动签到，失败原因为“无法获取签到手势”"))
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"自动签到失败，失败原因为“无法获取签到手势”\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    del user_list[uid]["sign_task_list"][str(aid)]
                    return 0
                sign_code = check_sign_code.groups()[0]
                if is_anti_fishing:
                    while True:
                        try:
                            async with session.get("https://mobilelearn.chaoxing.com/widget/sign/pcTeaSignController/getAttendList?activeId="+str(aid)+"&appType=15&classId="+str(class_id)+"&fid=0", headers=browser_headers, timeout=10) as resp:
                                res1 = json.loads(await resp.text())
                            break
                        except Exception as e:
                            logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                    student_count = res1["data"]["weiqian"]+res1["data"]["yiqian"]
                    asyncio.create_task(send_email("<p>【学习通在线自动签到系统手势签到通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到手势签到，签到手势为“"+sign_code+"”，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到。</p>", email, "学习通手势签到通知"))
                    asyncio.create_task(send_wechat_message(uid, "【学习通手势签到通知】 课程或班级“"+na+"”监测到手势签到，签到手势为“"+sign_code+"”，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到"))
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为手势签到，签到手势为“"+sign_code+"”，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    while True:
                        result = await anti_fishing_check_in_mode(student_count, session, aid)
                        if result is None:
                            asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到人数取消监控通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到手势签到，签到手势为“"+sign_code+"”，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控。</p>", email, "学习通签到人数取消监控通知"))
                            asyncio.create_task(send_wechat_message(uid, "【学习通签到人数取消监控通知】 课程或班级“"+na+"”监测到手势签到，签到手势为“"+sign_code+"”，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控"))
                            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为手势签到，签到手势为“"+sign_code+"”，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控\n"}), server_key, server_iv)
                            await send_message(sign_server_ws, encrypt)
                            del user_list[uid]["sign_task_list"][str(aid)]
                            return
                        elif result:
                            break
                        else:
                            await asyncio.sleep(2)
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"监测到已签人数已不少于未签人数，开始自动签到\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                else:
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为手势签到，签到手势为“"+sign_code+"”\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                sign_type = "手势签到，签到手势为“"+sign_code+"”"
                sign_type2 = "手势签到"
                _data = {
                    'name': user_list[uid]["name"],
                    'activeId': aid,
                    'uid': uid,
                    'signCode': sign_code
                }
            elif res['data']['otherId'] == 4:
                if res['data']['ifopenAddress'] == 1:
                    while True:
                        try:
                            async with session.get("https://mobilelearn.chaoxing.com/v2/apis/sign/getLocationLog?DB_STRATEGY=COURSEID&STRATEGY_PARA=courseId&courseId="+str(course_id)+"&classId="+str(_class_id), headers=chaoxing_headers, timeout=10) as resp:
                                rres = json.loads(await resp.text())
                            break
                        except Exception as e:
                            logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                    if rres["result"]:
                        is_find = False
                        for d in rres["data"]:
                            if str(d["activeid"]) == str(_aid):
                                set_address = str(d["address"])
                                set_longitude = str(d["longitude"])
                                set_latitude = str(d["latitude"])
                                is_find = True
                                break
                        if not is_find:
                            get_locationurl = "https://mobilelearn.chaoxing.com/pptSign/errorLocation?DB_STRATEGY=PRIMARY_KEY&STRATEGY_PARA=activeId&activeId="+str(aid)+"&uid="+str(uid)+"&location=%7B%22result%22%3A%201%2C%20%22latitude%22%3A%2039.5426%2C%20%22longitude%22%3A%20116.2329%2C%20%22address%22%3A%20%22%E4%B8%AD%E5%9B%BD%E5%8C%97%E4%BA%AC%E5%B8%82%22%7D&errortype=errorLocation2"
                            while True:
                                try:
                                    async with session.get(get_locationurl, headers=chaoxing_headers, timeout=10) as resp:
                                        rres_text = await resp.text()
                                    break
                                except Exception as e:
                                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                            if re.search(r'<input type="hidden" id="locationText" value="(.+)">', rres_text, re.I) is not None:
                                set_address = re.search(r'<input type="hidden" id="locationText" value="(.+)">', rres_text, re.I).groups()[0]
                                set_latitude = re.search(r'<input type="hidden" id="locationLatitude" value="(.+)">', rres_text, re.I).groups()[0]
                                set_longitude = re.search(r'<input type="hidden" id="locationLongitude" value="(.+)">', rres_text, re.I).groups()[0]
                            else:
                                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为指定了签到地点的位置签到，但无法获取指定位置信息\n"}), server_key, server_iv)
                                await send_message(sign_server_ws, encrypt)
                                asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到失败通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到指定了签到地点的位置签到，签到活动名称为“"+name_one+append_text+"”，但在线签到系统未能成功完成自动签到，失败原因为“无法获取指定位置信息”，这可能是由于您已签到过了。</p>", email, "学习通指定位置签到结果：签到失败"))
                                asyncio.create_task(send_wechat_message(uid, "【学习通指定位置签到结果：签到失败】 课程或班级“"+na+"”监测到指定了签到地点的位置签到，签到活动名称为“"+name_one+append_text+"”，但在线签到系统未能成功完成自动签到，失败原因为“无法获取指定位置信息”，这可能是由于您已签到过了"))
                                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"自动签到失败，失败原因为“无法获取指定位置信息”，您可能已经签到过了\n"}), server_key, server_iv)
                                await send_message(sign_server_ws, encrypt)
                                del user_list[uid]["sign_task_list"][str(aid)]
                                return 0
                    else:
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为指定了签到地点的位置签到，但无法获取指定位置信息\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                        asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到失败通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到指定了签到地点的位置签到，签到活动名称为“"+name_one+append_text+"”，但在线签到系统未能成功完成自动签到，失败原因为“无法获取指定位置信息”，这可能是由于您已签到过了。</p>", email, "学习通指定位置签到结果：签到失败"))
                        asyncio.create_task(send_wechat_message(uid, "【学习通指定位置签到结果：签到失败】 课程或班级“"+na+"”监测到指定了签到地点的位置签到，签到活动名称为“"+name_one+append_text+"”，但在线签到系统未能成功完成自动签到，失败原因为“无法获取指定位置信息”，这可能是由于您已签到过了"))
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"自动签到失败，失败原因为“无法获取指定位置信息”，您可能已经签到过了\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                        del user_list[uid]["sign_task_list"][str(aid)]
                        return 0
                    if is_anti_fishing:
                        while True:
                            try:
                                async with session.get("https://mobilelearn.chaoxing.com/widget/sign/pcTeaSignController/getAttendList?activeId="+str(aid)+"&appType=15&classId="+str(class_id)+"&fid=0", headers=browser_headers, timeout=10) as resp:
                                    res1 = json.loads(await resp.text())
                                break
                            except Exception as e:
                                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                        student_count = res1["data"]["weiqian"]+res1["data"]["yiqian"]
                        asyncio.create_task(send_email("<p>【学习通在线自动签到系统指定位置签到通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到指定了签到地点的位置签到，指定签到地点为“"+set_address+"”，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到。</p>", email, "学习通指定位置签到通知"))
                        asyncio.create_task(send_wechat_message(uid, "【学习通指定位置签到通知】 课程或班级“"+na+"”监测到指定了签到地点的位置签到，指定签到地点为“"+set_address+"”，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到"))
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为指定了签到地点的位置签到，指定签到地点为“"+set_address+"”，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                        while True:
                            result = await anti_fishing_check_in_mode(student_count, session, aid)
                            if result is None:
                                asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到人数取消监控通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到指定了签到地点的位置签到，指定签到地点为“"+set_address+"”，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控。</p>", email, "学习通签到人数取消监控通知"))
                                asyncio.create_task(send_wechat_message(uid, "【学习通签到人数取消监控通知】 课程或班级“"+na+"”监测到指定了签到地点的位置签到，指定签到地点为“"+set_address+"”，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控"))
                                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为指定了签到地点的位置签到，指定签到地点为“"+set_address+"”，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控\n"}), server_key, server_iv)
                                await send_message(sign_server_ws, encrypt)
                                del user_list[uid]["sign_task_list"][str(aid)]
                                return
                            elif result:
                                break
                            else:
                                await asyncio.sleep(2)
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"监测到已签人数已不少于未签人数，开始自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                    else:
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为指定了签到地点的位置签到，指定签到地点为“"+set_address+"”\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                    sign_type = "指定了签到地点的位置签到，指定签到地点为“"+set_address+"”"
                    sign_type2 = "指定位置签到"
                    _data = {
                        'name': user_list[uid]["name"],
                        'address': set_address,
                        'activeId': aid,
                        'uid': uid,
                        'longitude': set_longitude,
                        'latitude': set_latitude
                    }
                else:
                    if is_anti_fishing and is_embezzle and (info_type == "all" or info_type == "location"):
                        while True:
                            try:
                                async with session.get("https://mobilelearn.chaoxing.com/widget/sign/pcTeaSignController/getAttendList?activeId="+str(aid)+"&appType=15&classId="+str(class_id)+"&fid=0", headers=browser_headers, timeout=10) as resp:
                                    res1 = json.loads(await resp.text())
                                break
                            except Exception as e:
                                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                        student_count = res1["data"]["weiqian"]+res1["data"]["yiqian"]
                        asyncio.create_task(send_email("<p>【学习通在线自动签到系统普通位置签到通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到普通位置签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统将在监测到已签人数不少于未签人数后随机使用其他已签到同学的位置信息进行自动签到。</p>", email, "学习通普通位置签到通知"))
                        asyncio.create_task(send_wechat_message(uid, "【学习通普通位置签到通知】 课程或班级“"+na+"”监测到普通位置签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统将在监测到已签人数不少于未签人数后随机使用其他已签到同学的位置信息进行自动签到"))
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为普通位置签到，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统将在监测到已签人数不少于未签人数后随机使用其他已签到同学的位置信息进行自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                        while True:
                            result = await anti_fishing_check_in_mode(student_count, session, aid)
                            if result is None:
                                asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到人数取消监控通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到普通位置签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控。</p>", email, "学习通签到人数取消监控通知"))
                                asyncio.create_task(send_wechat_message(uid, "【学习通签到人数取消监控通知】 课程或班级“"+na+"”监测到普通位置签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控"))
                                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为普通位置签到，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控\n"}), server_key, server_iv)
                                await send_message(sign_server_ws, encrypt)
                                del user_list[uid]["sign_task_list"][str(aid)]
                                return
                            elif result:
                                break
                            else:
                                await asyncio.sleep(2)
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"监测到已签人数已不少于未签人数，开始自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                        result = await monitor_the_sign_in_of_other_students(session, "location", aid, class_id)
                        if result is None:
                            asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到取消通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到普通位置签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统在盗用签到信息时发现签到已过期或签到发布时长超过24小时，因此取消对当前签到活动进行签到。</p>", email, "学习通签到取消通知"))
                            asyncio.create_task(send_wechat_message(uid, "【学习通签到取消通知】 课程或班级“"+na+"”监测到普通位置签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统在盗用签到信息时发现签到已过期或签到发布时长超过24小时，因此取消对当前签到活动进行签到"))
                            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为普通位置签到，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统在盗用签到信息时发现签到已过期或签到发布时长超过24小时，因此取消对当前签到活动进行签到\n"}), server_key, server_iv)
                            await send_message(sign_server_ws, encrypt)
                            del user_list[uid]["sign_task_list"][str(aid)]
                            return
                        else:
                            use_name = result[0]
                            address = result[1]
                            longitude = result[2]
                            latitude = result[3]
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"随机使用"+use_name+"同学的位置信息进行自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                        append_text = "，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统随机使用"+use_name+"同学的位置信息进行签到"
                    elif is_anti_fishing:
                        while True:
                            try:
                                async with session.get("https://mobilelearn.chaoxing.com/widget/sign/pcTeaSignController/getAttendList?activeId="+str(aid)+"&appType=15&classId="+str(class_id)+"&fid=0", headers=browser_headers, timeout=10) as resp:
                                    res1 = json.loads(await resp.text())
                                break
                            except Exception as e:
                                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                        student_count = res1["data"]["weiqian"]+res1["data"]["yiqian"]
                        asyncio.create_task(send_email("<p>【学习通在线自动签到系统普通位置签到通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到普通位置签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到。</p>", email, "学习通普通位置签到通知"))
                        asyncio.create_task(send_wechat_message(uid, "【学习通普通位置签到通知】 课程或班级“"+na+"”监测到普通位置签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到"))
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为普通位置签到，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                        while True:
                            result = await anti_fishing_check_in_mode(student_count, session, aid)
                            if result is None:
                                asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到人数取消监控通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到普通位置签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控。</p>", email, "学习通签到人数取消监控通知"))
                                asyncio.create_task(send_wechat_message(uid, "【学习通签到人数取消监控通知】 课程或班级“"+na+"”监测到普通位置签到，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控"))
                                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为普通位置签到，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控\n"}), server_key, server_iv)
                                await send_message(sign_server_ws, encrypt)
                                del user_list[uid]["sign_task_list"][str(aid)]
                                return
                            elif result:
                                break
                            else:
                                await asyncio.sleep(2)
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"监测到已签人数已不少于未签人数，开始自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                    elif is_embezzle and (info_type == "all" or info_type == "location"):
                        asyncio.create_task(send_email("<p>【学习通在线自动签到系统普通位置签到通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到普通位置签到，签到活动名称为“"+name_one+"”，由于您启用了签到信息盗用模式，系统将在其他同学签到后随机使用其他已签到同学的位置信息进行自动签到。</p>", email, "学习通普通位置签到通知"))
                        asyncio.create_task(send_wechat_message(uid, "【学习通普通位置签到通知】 课程或班级“"+na+"”监测到普通位置签到，签到活动名称为“"+name_one+"”，由于您启用了签到信息盗用模式，系统将在其他同学签到后随机使用其他已签到同学的位置信息进行自动签到"))
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为普通位置签到，由于您启用了签到信息盗用模式，系统将在其他同学签到后随机使用其他已签到同学的位置信息进行自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                        result = await monitor_the_sign_in_of_other_students(session, "location", aid, class_id)
                        if result is None:
                            asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到取消通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到普通位置签到，签到活动名称为“"+name_one+"”，由于您启用了签到信息盗用模式，系统在盗用签到信息时发现签到已过期或签到发布时长超过24小时，因此取消对当前签到活动进行签到。</p>", email, "学习通签到取消通知"))
                            asyncio.create_task(send_wechat_message(uid, "【学习通签到取消通知】 课程或班级“"+na+"”监测到普通位置签到，签到活动名称为“"+name_one+"”，由于您启用了签到信息盗用模式，系统在盗用签到信息时发现签到已过期或签到发布时长超过24小时，因此取消对当前签到活动进行签到"))
                            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为普通位置签到，由于您启用了签到信息盗用模式，系统在盗用签到信息时发现签到已过期或签到发布时长超过24小时，因此取消对当前签到活动进行签到\n"}), server_key, server_iv)
                            await send_message(sign_server_ws, encrypt)
                            del user_list[uid]["sign_task_list"][str(aid)]
                            return
                        else:
                            use_name = result[0]
                            address = result[1]
                            longitude = result[2]
                            latitude = result[3]
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"随机使用"+use_name+"同学的位置信息进行自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                        append_text = "，由于您启用了签到信息盗用模式，系统随机使用"+use_name+"同学的位置信息进行签到"
                    elif address == "" or longitude == "" or latitude == "":
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为普通位置签到，但您未设置位置信息或信息不完整，将使用普通签到模式执行无位置信息自动签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                        longitude = "-1"
                        latitude = "-1"
                        append_text = "，由于您未设置位置信息或信息不完整，因此使用普通签到模式执行无位置信息自动签到"
                    else:
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为普通位置签到\n"}), server_key, server_iv)
                        await send_message(sign_server_ws, encrypt)
                    sign_type = sign_type2 = "普通位置签到"
                    _data = {
                        'name': user_list[uid]["name"],
                        'address': address,
                        'activeId': aid,
                        'uid': uid,
                        'longitude': longitude,
                        'latitude': latitude,
                    }
            elif res['data']['otherId'] == 5:
                while True:
                    try:
                        async with session.get("https://mobilelearn.chaoxing.com/widget/sign/pcTeaSignController/endSign?activeId="+str(aid)+"&classId="+str(class_id)+"&fid=&courseId="+str(course_id)+"&isTeacherViewOpen=1", headers=chaoxing_headers, timeout=10) as resp:
                            rres = await resp.text()
                        break
                    except Exception as e:
                        logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                check_sign_code = re.search(r'<input type="hidden" id="signCode" value="(\d+)" />', rres, re.I)
                if check_sign_code is None:
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为签到码签到，但无法获取签到码\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到失败通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到签到码签到，签到活动名称为“"+name_one+append_text+"”，但在线签到系统未能成功完成自动签到，失败原因为“无法获取签到码”。</p>", email, "学习通签到码签到结果：签到失败"))
                    asyncio.create_task(send_wechat_message(uid, "【学习通签到码签到结果：签到失败】 课程或班级“"+na+"”监测到签到码签到，签到活动名称为“"+name_one+append_text+"”，但在线签到系统未能成功完成自动签到，失败原因为“无法获取签到码”"))
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"自动签到失败，失败原因为“无法获取签到码”\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    del user_list[uid]["sign_task_list"][str(aid)]
                    return 0
                sign_code = check_sign_code.groups()[0]
                if is_anti_fishing:
                    while True:
                        try:
                            async with session.get("https://mobilelearn.chaoxing.com/widget/sign/pcTeaSignController/getAttendList?activeId="+str(aid)+"&appType=15&classId="+str(class_id)+"&fid=0", headers=browser_headers, timeout=10) as resp:
                                res1 = json.loads(await resp.text())
                            break
                        except Exception as e:
                            logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                    student_count = res1["data"]["weiqian"]+res1["data"]["yiqian"]
                    asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到码签到通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到签到码签到，签到码为“"+sign_code+"”，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到。</p>", email, "学习通签到码签到通知"))
                    asyncio.create_task(send_wechat_message(uid, "【学习通签到码签到通知】 课程或班级“"+na+"”监测到签到码签到，签到码为“"+sign_code+"”，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到"))
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为签到码签到，签到码为“"+sign_code+"”，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    while True:
                        result = await anti_fishing_check_in_mode(student_count, session, aid)
                        if result is None:
                            asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到人数取消监控通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到签到码签到，签到码为“"+sign_code+"”，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控。</p>", email, "学习通签到人数取消监控通知"))
                            asyncio.create_task(send_wechat_message(uid, "【学习通签到人数取消监控通知】 课程或班级“"+na+"”监测到签到码签到，签到码为“"+sign_code+"”，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控"))
                            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为签到码签到，签到码为“"+sign_code+"”，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期或签到发布时长超过24小时，因此取消了对当前签到活动的签到监控\n"}), server_key, server_iv)
                            await send_message(sign_server_ws, encrypt)
                            del user_list[uid]["sign_task_list"][str(aid)]
                            return
                        elif result:
                            break
                        else:
                            await asyncio.sleep(2)
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"监测到已签人数已不少于未签人数，开始自动签到\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                else:
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为签到码签到，签到码为“"+sign_code+"”\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                sign_type = "签到码签到，签到码为“"+sign_code+"”"
                sign_type2 = "签到码签到"
                _data = {
                    'name': user_list[uid]["name"],
                    'activeId': aid,
                    'uid': uid,
                    'signCode': sign_code
                }
            if user_list[uid]["port"] == 1 and not is_anti_fishing and not (is_embezzle and ((info_type == "all" and (sign_type == "拍照签到" or sign_type == "普通位置签到")) or (sign_type == "拍照签到" and info_type == "picture") or (sign_type == "普通位置签到" and info_type == "location"))):
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"等待9秒后开始预签到\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
                await asyncio.sleep(9)
            while True:
                try:
                    await session.get("https://mobilelearn.chaoxing.com/newsign/preSign?courseId="+str(course_id)+"&classId="+str(class_id)+"&activePrimaryId="+str(aid)+"&general=1&sys=1&ls=1&appType=15&&uid="+str(uid)+"&ut=s", headers=chaoxing_headers, timeout=10)
                    async with session.get("https://mobilelearn.chaoxing.com/pptSign/analysis?vs=1&DB_STRATEGY=RANDOM&aid="+str(aid), headers=chaoxing_headers, timeout=10) as resp:
                        test_res = await resp.text()
                    md5_pattern = re.compile(r'[a-f0-9]{32}')
                    _hash = md5_pattern.findall(test_res)[0]
                    await session.get("https://mobilelearn.chaoxing.com/pptSign/analysis2?DB_STRATEGY=RANDOM&code="+str(_hash), headers=chaoxing_headers, timeout=10)
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"预签到请求成功，等待1秒后开始签到\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    await asyncio.sleep(1)
                    async with session.post(url, headers=chaoxing_headers, data=_data, timeout=10) as resp:
                        text = await resp.text()
                    if text == "validate":
                        continue
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            if text == "请先登录再进行签到":
                asyncio.create_task(stop_reason(1, uid, name, email))
                return 1
            if text == "success":
                user_list[uid]["success_sign_num"] += 1
                asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到成功通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到"+sign_type+"，签到活动名称为“"+name_one+"”"+append_text+"，在线自动签到系统已成功完成自动签到。</p>", email, sign_type2+"结果：签到成功"))
                asyncio.create_task(send_wechat_message(uid, "【"+sign_type2+"结果：签到成功】 课程或班级“"+na+"”监测到"+sign_type+"，签到活动名称为“"+name_one+"”"+append_text+"，在线自动签到系统已成功完成自动签到"))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"自动签到成功\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
                if is_numing and user_list[uid]["success_sign_num"] >= sign_num:
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"定次签到模式已完成指定成功签到次数\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    asyncio.create_task(send_email("<p>【学习通在线自动签到系统停止监控通知】</p><p style=\"text-indent:2em;\">定次签到模式已完成指定成功签到次数，签到监控已停止。</p>", email, "学习通在线自动签到系统停止监控通知"))
                    asyncio.create_task(send_wechat_message(uid, "【学习通在线自动签到系统停止监控通知】 定次签到模式已完成指定成功签到次数，签到监控已停止"))
                    encrypt = await get_data_aes_encode(json.dumps({"result": 1, "type": "need_stop_sign", "uid": uid, "name": name}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
            elif text == "success2":
                asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到过期通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到"+sign_type+"，签到活动名称为“"+name_one+"”"+append_text+"，在线自动签到系统已成功完成自动签到，但学习通提示“签到过期”，请自行前往学习通查看签到情况。</p>", email, sign_type2+"结果：签到过期"))
                asyncio.create_task(send_wechat_message(uid, "【"+sign_type2+"结果：签到过期】 课程或班级“"+na+"”监测到"+sign_type+"，签到活动名称为“"+name_one+"”"+append_text+"，在线自动签到系统已成功完成自动签到，但学习通提示“签到过期”，请自行前往学习通查看签到情况"))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"自动签到成功，但学习通提示“签到过期”，请自行前往学习通查看签到情况\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
            else:
                asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到失败通知】</p><p style=\"text-indent:2em;\">课程或班级“"+na+"”监测到"+sign_type+"，签到活动名称为“"+name_one+"”"+append_text+"，但在线签到系统未能成功完成自动签到，失败原因为“"+text+"”。</p>", email, sign_type2+"结果：签到失败"))
                asyncio.create_task(send_wechat_message(uid, "【"+sign_type2+"结果：签到失败】 课程或班级“"+na+"”监测到"+sign_type+"，签到活动名称为“"+name_one+"”"+append_text+"，但在线签到系统未能成功完成自动签到，失败原因为“"+text+"”"))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"自动签到失败，失败原因为“"+text+"”\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
            del user_list[uid]["sign_task_list"][str(aid)]
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def anti_fishing_check_in_mode(student_count, session, aid, sign_type="class"):
    try:
        if sign_type == "class":
            while True:
                try:
                    async with session.get("https://mobilelearn.chaoxing.com/widget/sign/pcTeaSignController/getCount?activeId="+str(aid)+"&appType=15", headers=browser_headers) as resp:
                        res = json.loads(await resp.text())
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            if res["data"]["activeStatus"] != 1 or int(res["data"]["startTime"])+86400 < int(time.time()):
                return None
            elif res["data"]["yiqian"] >= student_count-res["data"]["yiqian"]:
                return True
            else:
                return False
        else:
            while True:
                try:
                    async with session.get("https://mobilelearn.chaoxing.com/sign/refeashSignList4Json?activeId="+str(aid)+"&lastTime=&lastId=0&pageNo=1&appType=1&type=1", headers=chaoxing_headers) as resp:
                        res = json.loads(await resp.text())
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            if res["activeStatus"] != 1:
                return None
            elif res["yiqianNum"] >= student_count-res["yiqianNum"]:
                return True
            else:
                return False
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def monitor_the_sign_in_of_other_students(session, sign_type, aid, classid, _type=True):
    try:
        while True:
            if sign_type == "group":
                while True:
                    try:
                        async with session.get("https://mobilelearn.chaoxing.com/sign/refeashSignList4Json?activeId="+str(aid)+"&lastTime=&lastId=0&pageNo=1&appType=1&type=0", headers=chaoxing_headers) as resp:
                            res = json.loads(await resp.text())
                        break
                    except Exception as e:
                        logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                if _type and res["activeStatus"] != 1:
                    return None
                elif res["list"]:
                    classmate_info = random.choice(res["list"])
                    if "title" not in classmate_info.keys():
                        title = ""
                    else:
                        title = str(classmate_info["title"])
                    return [str(classmate_info["name"]), title, str(classmate_info["longitude"]), str(classmate_info["latitude"])]
                else:
                    await asyncio.sleep(10)
                    continue
            else:
                while True:
                    try:
                        async with session.get("https://mobilelearn.chaoxing.com/widget/sign/pcTeaSignController/getCount?activeId="+str(aid)+"&appType=15", headers=browser_headers) as resp:
                            res = json.loads(await resp.text())
                        break
                    except Exception as e:
                        logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                if _type and (res["data"]["activeStatus"] != 1 or int(res["data"]["startTime"])+86400 < int(time.time())):
                    return None
                elif res["result"] and res["data"]["yiqian"] > 0:
                    if sign_type == "photo":
                        while True:
                            try:
                                async with session.get("https://mobilelearn.chaoxing.com/widget/sign/pcTeaSignController/getAttendList?activeId="+str(aid)+"&appType=15&classId="+str(classid)+"&fid=0", headers=browser_headers) as resp:
                                    res = json.loads(await resp.text())
                                break
                            except Exception as e:
                                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                        if res["result"]:
                            classmate_info = random.choice(res["data"]["yiqianList"])
                            return [classmate_info["name"], classmate_info["title"]]
                        else:
                            await asyncio.sleep(10)
                            continue
                    elif sign_type == "location":
                        while True:
                            try:
                                async with session.get("https://mobilelearn.chaoxing.com/pptSign/refeashSignList4Json2?activeId="+str(aid)+"&lastTime=&lastId=0&pageNo=1&appType=15&type=0", headers=browser_headers) as resp:
                                    res = json.loads(await resp.text())
                                break
                            except Exception as e:
                                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                        if res["activeStatus"]:
                            classmate_info = random.choice(res["list"])
                            return [classmate_info["name"], classmate_info["title"], classmate_info["longitude"], classmate_info["latitude"]]
                        else:
                            await asyncio.sleep(10)
                            continue
                else:
                    await asyncio.sleep(10)
                    continue
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def get_data_md5(_data):
    try:
        md5_digest = await asyncio.to_thread(md5, _data)
        return md5_digest.hexdigest()
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def get_data_base64_encode(_data):
    try:
        base64_encode_str = await asyncio.to_thread(base64.b64encode, _data)
        return base64_encode_str
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def get_data_aes_decode(_data, _key, _iv):
    try:
        if _data is None:
            return ""
        encrypted = await get_data_base64_decode(_data)
        cipher = await asyncio.to_thread(AES.new, bytes(_key, "utf-8"), AES.MODE_CBC, bytes(_iv, "utf-8"))
        decrypted = await asyncio.to_thread(cipher.decrypt, encrypted)
        return decrypted[:-ord(decrypted[len(decrypted)-1:])].decode("utf-8")
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))
        return ""


async def get_data_aes_encode(_data, _key, tiv):
    try:
        raw = bytes(_data, "utf-8")
        raw += (AES.block_size - len(raw) % AES.block_size) * bytes([AES.block_size - len(raw) % AES.block_size])
        cipher = await asyncio.to_thread(AES.new, bytes(_key, "utf-8"), AES.MODE_CBC, bytes(tiv, "utf-8"))
        encrypted = await asyncio.to_thread(cipher.encrypt, raw)
        return (await get_data_base64_encode(encrypted)).decode("utf-8")
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def sign_server_ws_monitor():
    global sign_server_ws, qrcode_sign_ws_get_heartbeat_message_time
    while True:
        try:
            async with websockets.connect("wss://cx.waadri.top/ws/othernode_server/websocket", ping_interval=10) as sign_server_ws:
                t = int(time.time())
                temp_list = []
                for d in qrcode_sign_list.keys():
                    temp_list.append(qrcode_sign_list[d]["aid"])
                encrypt = await get_data_aes_encode(node_name, server_key, server_iv)
                _data = {"t": t, "device_id": encrypt, "uuid": node_uuid, "qrcode_sign_list": temp_list, "password": node_password}
                encrypt = await get_data_aes_encode(json.dumps(_data), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
                while True:
                    message = await sign_server_ws.recv()
                    qrcode_sign_ws_get_heartbeat_message_time = time.time()
                    if message == "success":
                        logging.info("节点上线成功，节点名称："+node_name+"，节点uuid："+node_uuid+"，可在在线自动签到系统中使用本节点")
                    elif message == "duplicate_name":
                        logging.warning("您的节点名称与目前已接入节点的名称存在重复，请在配置文件中修改节点名称后重新启动本程序")
                        await sign_server_ws.close()
                        return 0
                    elif message != "ping":
                        try:
                            _data = json.loads(message)
                        except:
                            logging.debug(message)
                            logging.warning("收到非json数据，与节点服务器的连接断开")
                            await sign_server_ws.close()
                            continue
                        t = int(_data["t"])
                        if t+10 >= int(time.time()):
                            _data = await get_data_aes_decode(_data["data"], server_key, server_iv)
                            _data = json.loads(_data)
                            if _data["type"] == "start_sign":
                                if _data["uid"] not in list(user_list.keys()):
                                    result = await person_sign(_data["uid"], _data["name"], _data["username"], _data["student_number"], _data["password"], _data["schoolid"], _data["cookie"], _data["port"], _data["is_timing"], _data["is_numing"], _data["is_anti_fishing"], _data["is_embezzle"], _data["sign_num"], _data["info_type"], _data["timestamp"], _data["address"], _data["longitude"], _data["latitude"], _data["objectId"], _data["email"], _data["start_time"], _data["end_time"])
                                    if result:
                                        logging.info(_data["name"] + "启动签到监控")
                                        encrypt = await get_data_aes_encode(json.dumps({"result": 1, "status": _data["is_timing"], "type": "start_sign", "uid": _data["uid"], "port": _data["port"], "node_uuid": node_uuid, "name": _data["name"], "username": _data["username"], "student_number": _data["student_number"], "password": _data["password"], "schoolid": _data["schoolid"], "cookie": _data["cookie"], "is_timing": _data["is_timing"], "is_numing": _data["is_numing"], "is_anti_fishing": _data["is_anti_fishing"], "is_embezzle": _data["is_embezzle"], "sign_num": _data["sign_num"], "info_type": _data["info_type"], "start_time": _data["start_time"], "end_time": _data["end_time"], "timestamp": _data["timestamp"]}), server_key, server_iv)
                                        await send_message(sign_server_ws, encrypt)
                                    else:
                                        await stop_reason(1, str(_data["uid"]), _data["name"], _data["email"])
                                        encrypt = await get_data_aes_encode(json.dumps({"result": 0, "type": "start_sign", "uid": str(_data["uid"]), "name": _data["name"], "node_uuid": node_uuid}), server_key, server_iv)
                                        await send_message(sign_server_ws, encrypt)
                                else:
                                    encrypt = await get_data_aes_encode(json.dumps({"result": 1, "status": _data["is_timing"], "type": "start_sign", "uid": str(_data["uid"]), "port": user_list[_data["uid"]]["port"], "node_uuid": node_uuid, "name": user_list[_data["uid"]]["name"], "username": _data["username"], "student_number": _data["student_number"], "password": _data["password"], "schoolid": _data["schoolid"], "cookie": _data["cookie"], "is_timing": _data["is_timing"], "is_numing": _data["is_numing"], "is_anti_fishing": _data["is_anti_fishing"], "is_embezzle": _data["is_embezzle"], "sign_num": _data["sign_num"], "info_type": _data["info_type"], "start_time": _data["start_time"], "end_time": _data["end_time"], "timestamp": user_list[_data["uid"]]["timestamp"]}), server_key, server_iv)
                                    await send_message(sign_server_ws, encrypt)
                            elif _data["type"] == "online_start_sign":
                                diff = list(set(user_list.keys()).difference(set(_data["uid_list"])))
                                if diff:
                                    for u in diff:
                                        logging.info(user_list[u]["name"] + "停止签到监控")
                                        await remove_sign_info(u)
                                diff = list(set(_data["uid_list"]).difference(set(user_list.keys())))
                                if diff:
                                    for u in diff:
                                        for ll in _data["sign_list"]:
                                            if u == ll["uid"]:
                                                result = await person_sign(ll["uid"], ll["name"], ll["username"], ll["student_number"], ll["password"], ll["schoolid"], ll["cookie"], ll["port"], ll["is_timing"], ll["is_numing"], ll["is_anti_fishing"], ll["is_embezzle"], ll["sign_num"], ll["info_type"], ll["timestamp"], ll["address"], ll["longitude"], ll["latitude"], ll["objectId"], ll["email"], ll["start_time"], ll["end_time"])
                                                if result:
                                                    logging.info(ll["name"] + "启动签到监控")
                                                    encrypt = await get_data_aes_encode(json.dumps({"result": 1, "status": ll["is_timing"], "type": "online_start_sign", "uid": str(ll["uid"]), "port": ll["port"], "node": "1", "name": ll["name"], "username": ll["username"], "student_number": ll["student_number"], "password": ll["password"], "schoolid": ll["schoolid"], "cookie": ll["cookie"], "is_timing": ll["is_timing"], "is_numing": ll["is_numing"], "is_anti_fishing": ll["is_anti_fishing"], "is_embezzle": ll["is_embezzle"], "sign_num": ll["sign_num"], "info_type": ll["info_type"], "start_time": ll["start_time"], "end_time": ll["end_time"], "timestamp": ll["timestamp"]}), server_key, server_iv)
                                                    await send_message(sign_server_ws, encrypt)
                                                else:
                                                    await stop_reason(1, str(ll["uid"]), ll["name"], ll["email"])
                                                    encrypt = await get_data_aes_encode(json.dumps({"result": 0, "type": "start_sign", "uid": str(ll["uid"]), "name": ll["name"], "node": "1"}), server_key, server_iv)
                                                    await send_message(sign_server_ws, encrypt)
                            elif _data["type"] == "stop_sign":
                                await remove_sign_info(_data["uid"])
                                encrypt = await get_data_aes_encode(json.dumps({"result": 1, "type": "stop_sign", "uid": _data["uid"], "name": _data["name"]}), server_key, server_iv)
                                await send_message(sign_server_ws, encrypt)
                            elif _data["type"] == "force_stop_sign":
                                await remove_sign_info(_data["uid"])
                                encrypt = await get_data_aes_encode(json.dumps({"result": 1, "type": "force_stop_sign", "uid": _data["uid"], "name": _data["name"]}), server_key, server_iv)
                                await send_message(sign_server_ws, encrypt)
                            elif _data["type"] == "push_qrcode_info":
                                asyncio.create_task(get_qrcode_for_ws(_data["aid"], _data["qrcode_info"], _data["address"], _data["longitude"], _data["latitude"]))
        except websockets.ConnectionClosed:
            logging.warning("节点掉线，尝试重新上线...")
            await asyncio.sleep(1)
        except Exception as e:
            logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            logging.warning("节点掉线，尝试重新上线...")
            await asyncio.sleep(1)


async def check_sign_ws_heartbeat_message_time(ws):
    try:
        while True:
            if sign_server_ws == ws:
                if time.time() > qrcode_sign_ws_get_heartbeat_message_time+20:
                    if sign_server_ws.state == 1:
                        await sign_server_ws.close()
                    break
                await asyncio.sleep(1)
            else:
                break
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def get_data_url_unquote(_data):
    try:
        url_unquote_str = await asyncio.to_thread(urllib.parse.unquote, _data)
        return url_unquote_str
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def get_data_url_quote(_data):
    try:
        url_quote_str = await asyncio.to_thread(urllib.parse.quote, _data)
        return url_quote_str
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def sign_in_manually_ws(keys, session, name, username, password, schoolid, cookie, courseid, classid, aid, _aid, uid, qrcode_info, address, longitude, latitude, lesson_name, is_numing, sign_num, email, use_other_info=False, fail_reason="", other_name=""):
    try:
        enc_decode = await get_data_url_unquote(qrcode_info)
        enc_txt = enc_decode[enc_decode.find("&enc=")+5:]
        enc_code = enc_txt[:enc_txt.find("&")]
        location = await get_data_url_quote('{"result":1,"latitude":'+latitude+',"longitude":'+longitude+',"address":"'+address+'"}')
        url = "https://mobilelearn.chaoxing.com/pptSign/stuSignajax?enc="+str(enc_code)+"&name="+str(name)+"&activeId="+str(_aid)+"&uid="+str(uid)+"&clientip=&location="+location+"&appType=15"
        while True:
            try:
                await session.get(qrcode_info, headers=chaoxing_headers, timeout=10)
                async with session.get(url, headers=chaoxing_headers, timeout=10) as resp:
                    txt = await resp.text()
                if txt == "请先登录":
                    del qrcode_sign_list[keys]
                    await stop_reason(1, uid, name, email)
                    return
                elif "validate" in txt:
                    async with session.get("https://mobilelearn.chaoxing.com/pptSign/analysis?vs=1&DB_STRATEGY=RANDOM&aid="+str(_aid), headers=chaoxing_headers, timeout=10) as resp:
                        test_res = await resp.text()
                    md5_pattern = re.compile(r'[a-f0-9]{32}')
                    _hash = md5_pattern.findall(test_res)[0]
                    await session.get("https://mobilelearn.chaoxing.com/pptSign/analysis2?DB_STRATEGY=RANDOM&code="+str(_hash), headers=chaoxing_headers, timeout=10)
                    await asyncio.sleep(1)
                    async with session.get(url, headers=chaoxing_headers, timeout=10) as resp:
                        txt = await resp.text()
                    if "validate" in txt:
                        continue
                    break
                else:
                    break
            except Exception as e:
                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
        if txt == "success":
            del qrcode_sign_list[keys]
            user_list[str(uid)]["success_sign_num"] += 1
            if use_other_info:
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但自动签到失败，失败原因为“"+fail_reason+"”，系统随机使用"+other_name+"的位置信息再次进行自动签到，自动签到成功\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
                asyncio.create_task(send_email("<p>【学习通在线自动签到系统二维码签到成功通知】</p><p style=\"text-indent:2em;\">通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但自动签到失败，失败原因为“"+fail_reason+"”，系统随机使用"+other_name+"的位置信息再次进行自动签到，自动签到成功。</p>", email, "二维码签到结果：签到成功"))
                asyncio.create_task(send_wechat_message(uid, "【二维码签到结果：签到成功】 通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但自动签到失败，失败原因为“"+fail_reason+"”，系统随机使用"+other_name+"的位置信息再次进行自动签到，自动签到成功"))
            else:
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，自动签到成功\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
                asyncio.create_task(send_email("<p>【学习通在线自动签到系统二维码签到成功通知】</p><p style=\"text-indent:2em;\">通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，自动签到成功。</p>", email, "二维码签到结果：签到成功"))
                asyncio.create_task(send_wechat_message(uid, "【二维码签到结果：签到成功】 通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，自动签到成功"))
            if is_numing and user_list[uid]["success_sign_num"] >= sign_num:
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"定次签到模式已完成指定成功签到次数\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
                asyncio.create_task(send_email("<p>【学习通在线自动签到系统停止监控通知】</p><p style=\"text-indent:2em;\">定次签到模式已完成指定成功签到次数，签到监控已停止。</p>", email, "学习通在线自动签到系统停止监控通知"))
                asyncio.create_task(send_wechat_message(uid, "【学习通在线自动签到系统停止监控通知】 定次签到模式已完成指定成功签到次数，签到监控已停止"))
                encrypt = await get_data_aes_encode(json.dumps({"result": 1, "type": "need_stop_sign", "uid": uid, "name": name}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
        elif txt == "success2":
            del qrcode_sign_list[keys]
            if use_other_info:
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但自动签到失败，失败原因为“"+fail_reason+"”，系统随机使用"+other_name+"的位置信息再次进行自动签到，自动签到成功，但学习通提示“签到过期”，请自行前往学习通查看签到情况\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
                asyncio.create_task(send_email("<p>【学习通在线自动签到系统二维码签到过期通知】</p><p style=\"text-indent:2em;\">通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但自动签到失败，失败原因为“"+fail_reason+"”，系统随机使用"+other_name+"的位置信息再次进行自动签到，自动签到成功，但学习通提示“签到过期”，请自行前往学习通查看签到情况。</p>", email, "二维码签到结果：签到过期"))
                asyncio.create_task(send_wechat_message(uid, "【二维码签到结果：签到过期】 通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但自动签到失败，失败原因为“"+fail_reason+"”，系统随机使用"+other_name+"的位置信息再次进行自动签到，自动签到成功，但学习通提示“签到过期”，请自行前往学习通查看签到情况"))
            else:
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，自动签到成功，但学习通提示“签到过期”，请自行前往学习通查看签到情况\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
                asyncio.create_task(send_email("<p>【学习通在线自动签到系统二维码签到过期通知】</p><p style=\"text-indent:2em;\">通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，自动签到成功，但学习通提示“签到过期”，请自行前往学习通查看签到情况。</p>", email, "二维码签到结果：签到过期"))
                asyncio.create_task(send_wechat_message(uid, "【二维码签到结果：签到过期】 通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，自动签到成功，但学习通提示“签到过期”，请自行前往学习通查看签到情况"))
        elif txt == "您已签到过了":
            del qrcode_sign_list[keys]
            if use_other_info:
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但自动签到失败，失败原因为“"+fail_reason+"”，系统随机使用"+other_name+"的位置信息再次进行自动签到，但学习通提示“您已签到过了”，系统将不再获取该签到活动的签到二维码来为您签到\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
                asyncio.create_task(send_email("<p>【学习通在线自动签到系统二维码签到失败通知】</p><p style=\"text-indent:2em;\">通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但自动签到失败，失败原因为“"+fail_reason+"”，系统随机使用"+other_name+"的位置信息再次进行自动签到，但学习通提示“您已签到过了”，系统将不再获取该签到活动的签到二维码来为您签到。</p>", email, "二维码签到结果：签到失败"))
                asyncio.create_task(send_wechat_message(uid, "【二维码签到结果：签到失败】 通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但自动签到失败，失败原因为“"+fail_reason+"”，系统随机使用"+other_name+"的位置信息再次进行自动签到，但学习通提示“您已签到过了”，系统将不再获取该签到活动的签到二维码来为您签到"))
            else:
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但学习通提示“您已签到过了”，系统将不再获取该签到活动的签到二维码来为您签到\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
                asyncio.create_task(send_email("<p>【学习通在线自动签到系统二维码签到失败通知】</p><p style=\"text-indent:2em;\">通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但学习通提示“您已签到过了”，系统将不再获取该签到活动的签到二维码来为您签到。</p>", email, "二维码签到结果：签到失败"))
                asyncio.create_task(send_wechat_message(uid, "【二维码签到结果：签到失败】 通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但学习通提示“您已签到过了”，系统将不再获取该签到活动的签到二维码来为您签到"))
        else:
            if txt == "errorLocation1" or txt == "errorLocation2":
                while True:
                    try:
                        async with session.get("https://mobilelearn.chaoxing.com/pptSign/refeashSignList4Json2?activeId="+str(aid)+"&lastTime=&lastId=0&pageNo=1&appType=15&type=0", headers=browser_headers) as resp:
                            res = json.loads(await resp.text())
                        if res["list"]:
                            break
                        else:
                            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但自动签到失败，失败原因为“"+str(txt)+"”，您所选位置可能不在教师指定签到位置范围内，请使用微信小程序重新选择指定位置并扫描未过期的签到二维码，扫描后系统将继续尝试为您签到\n"}), server_key, server_iv)
                            await send_message(sign_server_ws, encrypt)
                            return
                    except Exception as e:
                        logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                if res["activeStatus"]:
                    classmate_info = random.choice(res["list"])
                    asyncio.create_task(sign_in_manually_ws(keys, session, name, username, password, schoolid, cookie, courseid, classid, aid, _aid, uid, qrcode_info, str(classmate_info["title"]), str(classmate_info["longitude"]), str(classmate_info["latitude"]), lesson_name, is_numing, sign_num, True, txt, str(classmate_info["name"])))
                else:
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但自动签到失败，失败原因为“"+str(txt)+"”，您所选位置可能不在教师指定签到位置范围内，请使用微信小程序重新选择指定位置并扫描未过期的签到二维码，扫描后系统将继续尝试为您签到\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
            else:
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但自动签到失败，失败原因为“"+str(txt)+"”，签到二维码可能已过期，请使用微信小程序重新扫描未过期的签到二维码，扫描后系统将继续尝试为您签到\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def get_message(ws, message, session, uid, name, username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, address, longitude, latitude, objectid, email):
    try:
        chatid = await getchatid(message)
        if chatid is None:
            return
        sessonend = 11
        while True:
            index = sessonend
            if chr(message[index]) != b"\x22".decode("utf-8"):
                index += 1
                break
            else:
                index += 1
            sessonend = message[index]+(message[index+1]-1)*0x80+index+2
            index += 2
            if sessonend < 0 or chr(message[index]).encode("utf-8") != b"\x08":
                index += 1
                break
            else:
                index += 1
            temp = await get_data_base64_encode(await buildreleasesession(chatid, message[index:index + 9]))
            await ws.send("[\""+temp.decode("utf-8")+"\"]")
            index += 10
            att = await getattachment(message, index, sessonend)
            if att is not None:
                if att["attachmentType"] == 15 and "atype" in att["att_chat_course"].keys() and (att["att_chat_course"]["atype"] == 2 or att["att_chat_course"]["atype"] == 0) and att["att_chat_course"]["type"] == 1 and att["att_chat_course"]["aid"] != 0:
                    if str(att["att_chat_course"]["aid"]) not in user_list[uid]["signed_in_list"]:
                        if "courseInfo" in att["att_chat_course"].keys():
                            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"收到来自课程或班级“"+att["att_chat_course"]["courseInfo"]["coursename"]+"”的签到活动，签到活动名称为“"+att["att_chat_course"]["title"]+"”\n"}), server_key, server_iv)
                            await send_message(sign_server_ws, encrypt)
                            user_list[uid]["sign_task_list"][str(att["att_chat_course"]["aid"])] = asyncio.create_task(signt(session, uid, name, att["att_chat_course"]["courseInfo"]["courseid"], att["att_chat_course"]["courseInfo"]["classid"], att["att_chat_course"]["aid"], username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, att["att_chat_course"]["title"], att["att_chat_course"]["courseInfo"]["coursename"], address, longitude, latitude, objectid, email))
                        elif att["att_chat_course"]["atype"] == 2:
                            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"收到来自群聊的签到活动，签到活动名称为“"+att["att_chat_course"]["title"]+"”\n"}), server_key, server_iv)
                            await send_message(sign_server_ws, encrypt)
                            user_list[uid]["sign_task_list"][str(att["att_chat_course"]["aid"])] = asyncio.create_task(group_signt(session, uid, name, att["att_chat_course"]["aid"], is_numing, is_anti_fishing, is_embezzle, sign_num, att["att_chat_course"]["title"], address, longitude, latitude, objectid, email))
            break
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def group_signt(session, uid, name, aid, is_numing, is_anti_fishing, is_embezzle, sign_num, name_one, address, longitude, latitude, objectid, email):
    try:
        if longitude == "" or latitude == "":
            longitude = "-1"
            latitude = "-1"
        user_list[uid]["signed_in_list"].append(str(aid))
        use_txt = ""
        if is_anti_fishing and is_embezzle:
            while True:
                try:
                    async with session.get("https://mobilelearn.chaoxing.com/sign/autoRefeashSignList4Json?activeId="+str(aid)+"&appType=1", headers=chaoxing_headers, timeout=10) as resp:
                        res1 = json.loads(await resp.text())
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            student_count = res1["yiqianNum"]+res1["weiqianNum"]
            asyncio.create_task(send_email("<p>【学习通在线自动签到系统群聊签到通知】</p><p style=\"text-indent:2em;\">收到来自群聊的签到活动，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统将在监测到已签人数不少于未签人数后随机使用其他已签到同学的签到信息进行自动签到。</p>", email, "学习通群聊签到通知"))
            asyncio.create_task(send_wechat_message(uid, "【学习通群聊签到通知】 收到来自群聊的签到活动，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统将在监测到已签人数不少于未签人数后随机使用其他已签到同学的签到信息进行自动签到"))
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"由于您启用了反钓鱼签到模式和签到信息盗用模式，系统将在监测到已签人数不少于未签人数后随机使用其他已签到同学的签到信息进行自动签到\n"}), server_key, server_iv)
            await send_message(sign_server_ws, encrypt)
            while True:
                result = await anti_fishing_check_in_mode(student_count, session, aid, sign_type="group")
                if result is None:
                    asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到人数取消监控通知】</p><p style=\"text-indent:2em;\">收到来自群聊的签到活动，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统在监测签到人数时发现签到已过期，因此取消了对当前签到活动的签到监控。</p>", email, "学习通签到人数取消监控通知"))
                    asyncio.create_task(send_wechat_message(uid, "【学习通签到人数取消监控通知】 收到来自群聊的签到活动，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统在监测签到人数时发现签到已过期，因此取消了对当前签到活动的签到监控"))
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"由于您启用了反钓鱼签到模式和签到信息盗用模式，系统在监测签到人数时发现签到已过期，因此取消了对当前签到活动的签到监控\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    del user_list[uid]["sign_task_list"][str(aid)]
                    return
                elif result:
                    break
                else:
                    await asyncio.sleep(2)
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"监测到已签人数已不少于未签人数，开始自动签到\n"}), server_key, server_iv)
            await send_message(sign_server_ws, encrypt)
            result = await monitor_the_sign_in_of_other_students(session, "group", aid, "")
            if result is None:
                asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到取消通知】</p><p style=\"text-indent:2em;\">收到来自群聊的签到活动，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统在盗用签到信息时发现签到已过期，因此取消对当前签到活动进行签到。</p>", email, "学习通签到取消通知"))
                asyncio.create_task(send_wechat_message(uid, "【学习通签到取消通知】 收到来自群聊的签到活动，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统在盗用签到信息时发现签到已过期，因此取消对当前签到活动进行签到"))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"由于您启用了反钓鱼签到模式和签到信息盗用模式，系统在盗用签到信息时发现签到已过期，因此取消对当前签到活动进行签到\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
                del user_list[uid]["sign_task_list"][str(aid)]
                return
            else:
                use_name = result[0]
                objectid = result[1]
                address = result[1]
                longitude = result[2]
                latitude = result[3]
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"随机使用"+use_name+"同学的签到信息进行自动签到\n"}), server_key, server_iv)
            await send_message(sign_server_ws, encrypt)
            use_txt = "，由于您启用了反钓鱼签到模式和签到信息盗用模式，系统随机使用"+use_name+"同学的签到信息进行签到"
        elif is_anti_fishing:
            while True:
                try:
                    async with session.get("https://mobilelearn.chaoxing.com/sign/autoRefeashSignList4Json?activeId="+str(aid)+"&appType=1", headers=chaoxing_headers, timeout=10) as resp:
                        res1 = json.loads(await resp.text())
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            student_count = res1["yiqianNum"]+res1["weiqianNum"]
            asyncio.create_task(send_email("<p>【学习通在线自动签到系统群聊签到通知】</p><p style=\"text-indent:2em;\">收到来自群聊的签到活动，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到。</p>", email, "学习通群聊签到通知"))
            asyncio.create_task(send_wechat_message(uid, "【学习通群聊签到通知】 收到来自群聊的签到活动，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到"))
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"由于您启用了反钓鱼签到模式，系统将在监测到已签人数不少于未签人数后自动签到\n"}), server_key, server_iv)
            await send_message(sign_server_ws, encrypt)
            while True:
                result = await anti_fishing_check_in_mode(student_count, session, aid, sign_type="group")
                if result is None:
                    asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到人数取消监控通知】</p><p style=\"text-indent:2em;\">收到来自群聊的签到活动，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期，因此取消了对当前签到活动的签到监控。</p>", email, "学习通签到人数取消监控通知"))
                    asyncio.create_task(send_wechat_message(uid, "【学习通签到人数取消监控通知】 收到来自群聊的签到活动，签到活动名称为“"+name_one+"”，由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期，因此取消了对当前签到活动的签到监控"))
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"由于您启用了反钓鱼签到模式，系统在监测签到人数时发现签到已过期，因此取消了对当前签到活动的签到监控\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    del user_list[uid]["sign_task_list"][str(aid)]
                    return
                elif result:
                    break
                else:
                    await asyncio.sleep(2)
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"监测到已签人数已不少于未签人数，开始自动签到\n"}), server_key, server_iv)
            await send_message(sign_server_ws, encrypt)
        elif is_embezzle:
            asyncio.create_task(send_email("<p>【学习通在线自动签到系统群聊签到通知】</p><p style=\"text-indent:2em;\">收到来自群聊的签到活动，签到活动名称为“"+name_one+"”，由于您启用了签到信息盗用模式，系统将在其他同学签到后随机使用其他已签到同学的签到信息进行自动签到。</p>", email, "学习通群聊签到通知"))
            asyncio.create_task(send_wechat_message(uid, "【学习通群聊签到通知】 收到来自群聊的签到活动，签到活动名称为“"+name_one+"”，由于您启用了签到信息盗用模式，系统将在其他同学签到后随机使用其他已签到同学的签到信息进行自动签到"))
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"由于您启用了签到信息盗用模式，系统将在其他同学签到后随机使用其他已签到同学的签到信息进行自动签到\n"}), server_key, server_iv)
            await send_message(sign_server_ws, encrypt)
            result = await monitor_the_sign_in_of_other_students(session, "group", aid, "")
            if result is None:
                asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到取消通知】</p><p style=\"text-indent:2em;\">收到来自群聊的签到活动，签到活动名称为“"+name_one+"”，由于您启用了签到信息盗用模式，系统在盗用签到信息时发现签到已过期或签到发布时长超过24小时，因此取消对当前签到活动进行签到。</p>", email, "学习通签到取消通知"))
                asyncio.create_task(send_wechat_message(uid, "【学习通签到取消通知】 收到来自群聊的签到活动，签到活动名称为“"+name_one+"”，由于您启用了签到信息盗用模式，系统在盗用签到信息时发现签到已过期或签到发布时长超过24小时，因此取消对当前签到活动进行签到"))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"由于您启用了签到信息盗用模式，系统在盗用签到信息时发现签到已过期或签到发布时长超过24小时，因此取消对当前签到活动进行签到\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
                del user_list[uid]["sign_task_list"][str(aid)]
                return
            else:
                use_name = result[0]
                objectid = result[1]
                address = result[1]
                longitude = result[2]
                latitude = result[3]
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"随机使用"+use_name+"同学的签到信息进行自动签到\n"}), server_key, server_iv)
            await send_message(sign_server_ws, encrypt)
            use_txt = "，由于您启用了签到信息盗用模式，系统随机使用"+use_name+"同学的签到信息进行签到"
        else:
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"等待10秒后开始自动签到\n"}), server_key, server_iv)
            await send_message(sign_server_ws, encrypt)
            await asyncio.sleep(10)
        async with session.get("https://mobilelearn.chaoxing.com/sign/stuSignajax?activeId=" + str(aid) +"&uid=" + str(uid) +"&latitude=" + latitude +"&longitude=" + longitude +"&address=" + address +"&fid=" + user_list[uid]["schoolid"] +"&objectId=" + objectid, headers=browser_headers) as resp:
            info = await resp.text()
        if info == "success":
            user_list[uid]["success_sign_num"] += 1
            asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到成功通知】</p><p style=\"text-indent:2em;\">收到来自群聊的签到活动，签到活动名称为“"+name_one+"”"+use_txt+"，在线签到系统已成功完成自动签到。</p>", email, "群聊签到结果：签到成功"))
            asyncio.create_task(send_wechat_message(uid, "【在线自动签到系统签到结果：签到成功】 收到来自群聊的签到活动，签到活动名称为“"+name_one+"”"+use_txt+"，在线签到系统已成功完成自动签到"))
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"自动签到成功\n"}), server_key, server_iv)
            await send_message(sign_server_ws, encrypt)
            if is_numing and user_list[uid]["success_sign_num"] >= sign_num:
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"定次签到模式已完成指定成功签到次数\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
                asyncio.create_task(send_email("<p>【学习通在线自动签到系统停止监控通知】</p><p style=\"text-indent:2em;\">定次签到模式已完成指定成功签到次数，签到监控已停止。</p>", email, "学习通在线自动签到系统停止监控通知"))
                asyncio.create_task(send_wechat_message(uid, "【学习通在线自动签到系统停止监控通知】 定次签到模式已完成指定成功签到次数，签到监控已停止"))
                encrypt = await get_data_aes_encode(json.dumps({"result": 1, "type": "need_stop_sign", "uid": uid, "name": name}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
        else:
            asyncio.create_task(send_email("<p>【学习通在线自动签到系统签到失败通知】</p><p style=\"text-indent:2em;\">收到来自群聊的签到活动，签到活动名称为“"+name_one+"”"+use_txt+"，但在线自动签到系统未能成功完成自动签到，失败原因为“"+info+"”。</p>", email, "在线自动签到系统签到结果：签到失败"))
            asyncio.create_task(send_wechat_message(uid, "【在线自动签到系统签到结果：签到失败】 收到来自群聊的签到活动，签到活动名称为“"+name_one+"”"+use_txt+"，但在线自动签到系统未能成功完成自动签到，失败原因为“"+info+"”"))
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"自动签到失败，失败原因为“"+info+"”\n"}), server_key, server_iv)
            await send_message(sign_server_ws, encrypt)
        del user_list[uid]["sign_task_list"][str(aid)]
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def getattachment(byte, start, end):
    try:
        start = await bytes_index_of(byte, BytesAttachment, start, end)
        if start == -1:
            return None
        start += len(BytesAttachment)
        length = byte[start]+(byte[start+1] - 1) * 0x80
        start += 2
        s = start
        start += length
        e = start
        j = json.loads(byte[s:e].decode("utf-8"))
        return None if start > end else j
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def bytes_index_of(byte, value, start=0, end=0):
    try:
        length = len(value)
        len_bytes = len(byte)
        if length == 0 or len_bytes == 0:
            return -1
        first = value[0]
        for i in range(start, len_bytes if end == 0 else end):
            if byte[i] != first:
                continue
            is_return = True
            for j in range(1, length):
                if byte[i+j] == value[j]:
                    continue
                is_return = False
                break
            if is_return:
                return i
        return -1
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def buildreleasesession(chatid, session):
    try:
        return bytearray([0x08, 0x00, 0x40, 0x00, 0x4a])+chr(len(chatid)+38).encode("utf-8")+b"\x10"+session+bytearray([0x1a, 0x29, 0x12])+chr(len(chatid)).encode("utf-8")+chatid.encode("utf-8")+bytesend+bytearray([0x58, 0x00])
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def first_get_taskinfo(ws, message):
    try:
        if await getchatid(message) is None:
            return
        chatid_list = re.findall(b'\\x12-\\n\\)\\x12\\x0f(\\d+)\\x1a\\x16conference.easemob.com\\x10', message)
        for ID in chatid_list:
            temp = await get_data_base64_encode(b"\x08\x00@\x00J+\x1a)\x12\x0f"+ID+b"\x1a\x16conference.easemob.comX\x00")
            await ws.send("[\""+temp.decode("utf-8")+"\"]")
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def getchatid(byte):
    try:
        index = await bytes_last_index_of(byte, bytesend)
        if index == -1:
            return None
        i = byte[:index].rfind(bytes([0x12]))
        if i == -1:
            return None
        length = byte[i+1]
        return byte[i+2: index].decode("utf-8") if i+2+length == index else None
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def bytes_last_index_of(byte, value, start=0, end=0):
    try:
        length = len(value)
        len_bytes = len(byte)
        if length == 0 or len_bytes == 0:
            return -1
        last = value[-1]
        for i in range(len_bytes - 1 if end == 0 else end - 1, start - 1, -1):
            if byte[i] != last:
                continue
            is_return = True
            for j in range(length - 2, -1, -1):
                if byte[i - length+j+1] == value[j]:
                    continue
                is_return = False
                break
            if is_return:
                return i - length+1
        return -1
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def get_taskinfo(ws, message):
    try:
        if await getchatid(message) is None:
            return
        mess2 = message.decode("utf-8")
        temp = ""
        for i in range(len(mess2)):
            if i == 3:
                temp += b"\x00".decode("utf-8")
            elif i == 6:
                temp += b"\x1a".decode("utf-8")
            else:
                temp += mess2[i]
        mess2 = temp+bytearray([0x58, 0x00]).decode("utf-8")
        temp = await get_data_base64_encode(mess2.encode("utf-8"))
        await ws.send("[\""+temp.decode("utf-8")+"\"]")
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def login(ws, session, uid, name, email):
    try:
        while True:
            try:
                async with session.post("https://a1-vip6.easemob.com/cx-dev/cxstudy/token", headers=browser_headers, data=json.dumps({"grant_type": "password", "password": user_list[uid]["impassword"], "username": user_list[uid]["imusername"]}), timeout=10) as resp:
                    res = json.loads(await resp.text())
                break
            except Exception as e:
                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
        if "error" not in res.keys():
            usuid = res["user"]["username"]
            im_token = res["access_token"]
            timestamp = str(int(time.time() * 1000))
            temp = await get_data_base64_encode(b"\x08\x00\x12"+chr(52+len(usuid)).encode("utf-8")+b"\x0a\x0e"+"cx-dev#cxstudy".encode("utf-8")+b"\x12"+chr(len(usuid)).encode("utf-8")+usuid.encode("utf-8")+b"\x1a\x0b"+"easemob.com".encode("utf-8")+b"\x22\x13"+("webim_"+timestamp).encode("utf-8")+b"\x1a\x85\x01"+"$t$".encode("utf-8")+im_token.encode("utf-8")+b"\x40\x03\x4a\xc0\x01\x08\x10\x12\x05\x33\x2e\x30\x2e\x30\x28\x00\x30\x00\x4a\x0d"+timestamp.encode("utf-8")+b"\x62\x05\x77\x65\x62\x69\x6d\x6a\x13\x77\x65\x62\x69\x6d\x5f"+timestamp.encode("utf-8")+b"\x72\x85\x01\x24\x74\x24"+im_token.encode("utf-8")+b"\x50\x00\x58\x00")
            _data = "[\"" + temp.decode("utf-8") + "\"]"
            await ws.send(_data)
        else:
            async with aiofiles.open("/root/temp.txt", "a") as _file:
                loops = asyncio.get_running_loop()
                await loops.run_in_executor(None, portalocker.lock, _file, portalocker.LOCK_EX)
                await _file.write(datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+str(await resp.text())+"\n")
                await loops.run_in_executor(None, portalocker.unlock, _file)
            asyncio.create_task(stop_reason(1, uid, name, email))
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def remove_sign_info(uid):
    try:
        for k in list(qrcode_sign_list.keys()):
            if str(uid) == str(qrcode_sign_list[k]["uid"]):
                del qrcode_sign_list[k]
        if uid in user_list.keys():
            if user_list[uid]["port"] == 1 and "ws_sign_heartbeat" in user_list[uid].keys() and not user_list[uid]["ws_sign_heartbeat"].done():
                    user_list[uid]["ws_sign_heartbeat"].cancel()
            for s in list(user_list[uid]["sign_task_list"].keys()):
                if not user_list[uid]["sign_task_list"][s].done():
                    user_list[uid]["sign_task_list"][s].cancel()
            if not user_list[uid]["main_sign_task"].done():
                user_list[uid]["main_sign_task"].cancel()
            await user_list[uid]["session"].close()
            logging.info(user_list[uid]["name"]+"停止签到监控")
            del user_list[uid]
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def connect(session, uid, name, username, password, schoolid, cookie, is_timing, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, _start_time, end_time, address, longitude, latitude, objectid, email):
    try:
        if is_timing:
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"定时签到模式已启用，系统将在"+datetime.datetime.fromtimestamp(_start_time).strftime("%Y-%m-%d %H:%M:%S")+"启动签到监控\n"}), server_key, server_iv)
            await send_message(sign_server_ws, encrypt)
            asyncio.create_task(check_sign_time(uid, name, end_time, email))
        while is_timing and time.time() < _start_time:
            await asyncio.sleep(1)
        while True:
            try:
                ws_str1 = str(int(random.random()*1000))
                ws_str2 = ''.join(random.choices("abcdefghijklmnopqrstuvwxyz012345", k=8))
                async with websockets.connect("wss://im-api-vip6-v2.easemob.com/ws/"+ws_str1+"/"+ws_str2+"/websocket", ping_interval=None, ping_timeout=None) as ws:
                    user_list[uid]["ws_heartbeat_time"] = time.time()
                    user_list[uid]["ws_sign_heartbeat"] = asyncio.create_task(check_ws_heartbeat_message_time(ws, uid))
                    while True:
                        if uid in user_list.keys():
                            user_list[uid]["ws_heartbeat_time"] = time.time()
                        else:
                            return
                        message = await ws.recv()
                        if message == "o":
                            await login(ws, session, uid, name, email)
                        elif message[0] == "a":
                            mess = json.loads(message[1:])[0]
                            mess = await get_data_base64_decode(mess)
                            if len(mess) < 5:
                                return
                            if mess[:5] == b"\x08\x00\x40\x02\x4a":
                                await get_taskinfo(ws, mess)
                            elif mess[:5] == b"\x08\x00\x40\x01\x4a":
                                await first_get_taskinfo(ws, mess)
                            elif mess[:5] == b"\x08\x00@\x03J":
                                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"与学习通服务器的websockets连接成功，正在监听签到活动\n"}), server_key, server_iv)
                                await send_message(sign_server_ws, encrypt)
                                await ws.send("[\"CABAAVgA\"]")
                            else:
                                await get_message(ws, mess, session, uid, name, username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, address, longitude, latitude, objectid, email)
            except websockets.ConnectionClosed:
                if "ws_sign_heartbeat" in user_list[uid].keys() and not user_list[uid]["ws_sign_heartbeat"].done():
                    user_list[uid]["ws_sign_heartbeat"].cancel()
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"与学习通服务器的websockets连接断开，正在重连……\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
            except Exception as e:
                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                if "ws_sign_heartbeat" in user_list[uid].keys() and not user_list[uid]["ws_sign_heartbeat"].done():
                    user_list[uid]["ws_sign_heartbeat"].cancel()
                await asyncio.sleep(1)
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"与学习通服务器的websockets连接断开，正在重连……\n"}), server_key, server_iv)
                await send_message(sign_server_ws, encrypt)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def check_ws_heartbeat_message_time(ws, uid):
    try:
        while True:
            if time.time() > user_list[uid]["ws_heartbeat_time"]+60:
                if ws.state == 1:
                    await ws.close()
                break
            await asyncio.sleep(1)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def check_sign_time(uid, name, end_time, email):
    try:
        while end_time > int(time.time()):
            if uid in user_list.keys():
                await asyncio.sleep(1)
            else:
                return
        asyncio.create_task(send_email("<p>【学习通在线自动签到系统停止监控通知】</p><p style=\"text-indent:2em;\">定时签到模式所指定监控停止时间已到，签到监控已停止。</p>", email, "学习通在线自动签到系统停止监控通知"))
        asyncio.create_task(send_wechat_message(uid, "【学习通在线自动签到系统停止监控通知】 定时签到模式所指定监控停止时间已到，签到监控已停止"))
        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"定时签到模式所指定监控停止时间已到\n"}), server_key, server_iv)
        await send_message(sign_server_ws, encrypt)
        encrypt = await get_data_aes_encode(json.dumps({"result": 1, "type": "stop_sign", "uid": uid, "name": name}), server_key, server_iv)
        await send_message(sign_server_ws, encrypt)
        await remove_sign_info(uid)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def start_sign(session, uid, name, username, password, schoolid, cookie, is_timing, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, _start_time, end_time, address, longitude, latitude, objectid, email):
    try:
        if is_timing:
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"定时签到模式已启用，系统将在"+datetime.datetime.fromtimestamp(_start_time).strftime("%Y-%m-%d %H:%M:%S")+"启动签到监控\n"}), server_key, server_iv)
            await send_message(sign_server_ws, encrypt)
            asyncio.create_task(check_sign_time(uid, name, end_time, email))
        while is_timing and time.time() < _start_time:
            await asyncio.sleep(1)
        user_list[uid]["clazzdata"] = []
        while True:
            try:
                async with session.post("https://a1-vip6.easemob.com/cx-dev/cxstudy/token", headers=browser_headers, data=json.dumps({"grant_type": "password", "password": user_list[uid]["impassword"], "username": user_list[uid]["imusername"]}), timeout=10) as resp:
                    res = json.loads(await resp.text())
                break
            except Exception as e:
                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
        if "error" in res.keys():
            await stop_reason(1, uid, name, email)
            return
        token = res["access_token"]
        imuid = res["user"]["username"]
        async with session.get("https://a1-vip6.easemob.com/cx-dev/cxstudy/users/"+imuid+"/joined_chatgroups?detail=true&version=v3&pagenum=1&pagesize=10000", headers={"Authorization": "Bearer "+token, "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.69 Safari/537.36"}) as resp:
            r = json.loads(await resp.text())
        if "error" in r.keys():
            await stop_reason(2, uid, name, email)
            return
        cdata = r["data"]
        for item in cdata:
            if item["description"] != "" and item["description"] != "面对面群聊":
                class_data = json.loads(item["description"])
                if (item['permission'] == 'member' or item['permission'] == 'admin') and "courseInfo" in class_data.keys():
                    if item["name"] == "":
                        course_name = class_data["courseInfo"]["coursename"]
                    else:
                        course_name = item["name"]
                    pushdata = {"courseid": class_data["courseInfo"]["courseid "], "name": course_name, "classid": class_data["courseInfo"]["classid"]}
                    user_list[uid]["clazzdata"].append(pushdata)
        rt = 0
        if user_list[uid]["port"] == 2:
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"课程和班级列表获取成功，共获取到"+str(len(user_list[uid]["clazzdata"]))+"条课程和班级数据，签到监控已启动，当前监控接口为接口2（APP端接口）\n"}), server_key, server_iv)
            await send_message(sign_server_ws, encrypt)
        elif user_list[uid]["port"] == 3:
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"课程和班级列表获取成功，共获取到"+str(len(user_list[uid]["clazzdata"]))+"条课程和班级数据，签到监控已启动，当前监控接口为接口3（网页端接口）\n"}), server_key, server_iv)
            await send_message(sign_server_ws, encrypt)
        elif user_list[uid]["port"] == 4:
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"课程和班级列表获取成功，共获取到"+str(len(user_list[uid]["clazzdata"]))+"条课程和班级数据，签到监控已启动，当前监控接口为接口4（教师端接口）\n"}), server_key, server_iv)
            await send_message(sign_server_ws, encrypt)
        while True:
            for _data in user_list[uid]["clazzdata"]:
                na = _data['name']
                if user_list[uid]["port"] == 2:
                    rt = await interface_two(session, uid, name, _data["courseid"], _data["classid"], username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, na, address, longitude, latitude, objectid, email)
                elif user_list[uid]["port"] == 3:
                    rt = await interface_three(session, uid, name, _data["courseid"], _data["classid"], username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, na, address, longitude, latitude, objectid, email)
                elif user_list[uid]["port"] == 4:
                    rt = await interface_four(session, uid, name, _data["courseid"], _data["classid"], username, password, schoolid, cookie, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, na, address, longitude, latitude, objectid, email)
                if rt == 1:
                    await session.close()
                    return
            if user_list[uid]["port"] == 4:
                await asyncio.sleep(20)
            else:
                await asyncio.sleep(60)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def person_sign(uid, name, username, student_number, password, schoolid, cookie, port, is_timing, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, timestamp, address, longitude, latitude, objectid, email, _start_time, end_time):
    try:
        session = aiohttp.ClientSession()
        if password != "":
            while True:
                try:
                    async with session.get("https://passport2.chaoxing.com/api/login?name={}&pwd={}&schoolid=&verify=0".format(username, password), headers=chaoxing_headers, timeout=10) as resp:
                        status = json.loads(await resp.text())
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            if status["result"]:
                while True:
                    try:
                        async with session.get("https://sso.chaoxing.com/apis/login/userLogin4Uname.do?ft=true", headers=browser_headers, timeout=10) as resp:
                            status2 = json.loads(await resp.text())
                        break
                    except Exception as e:
                        logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                if status2["result"]:
                    if status2["msg"]["fid"] == 0:
                        fid = ""
                    else:
                        fid = str(status2["msg"]["fid"])
                    user_list[uid] = {"error_num": 0, "port": port, "timestamp": timestamp, "fid": schoolid, "session": session, "imusername": status2["msg"]["accountInfo"]["imAccount"]["username"], "impassword": status2["msg"]["accountInfo"]["imAccount"]["password"], "name": status["realname"], "username": username, "password": password, "schoolid": fid, "cookie": cookie, "signed_in_list": [], "success_sign_num": 0, "sign_task_list": {}}
                    if port == 1:
                        user_list[uid]["main_sign_task"] = asyncio.create_task(connect(session, uid, name, username, password, schoolid, cookie, is_timing, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, _start_time, end_time, address, longitude, latitude, objectid, email))
                    else:
                        user_list[uid]["main_sign_task"] = asyncio.create_task(start_sign(session, uid, name, username, password, schoolid, cookie, is_timing, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, _start_time, end_time, address, longitude, latitude, objectid, email))
                    return True
                elif cookie:
                    while True:
                        try:
                            async with session.get("https://sso.chaoxing.com/apis/login/userLogin4Uname.do?ft=true", headers=browser_headers, cookies=cookie, timeout=10) as resp:
                                status2 = json.loads(await resp.text())
                            break
                        except Exception as e:
                            logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                    if status2["result"]:
                        if status2["msg"]["fid"] == 0:
                            fid = ""
                        else:
                            fid = str(status2["msg"]["fid"])
                        user_list[uid] = {"error_num": 0, "port": port, "timestamp": timestamp, "fid": schoolid, "session": session, "imusername": status2["msg"]["accountInfo"]["imAccount"]["username"], "impassword": status2["msg"]["accountInfo"]["imAccount"]["password"], "name": status2["msg"]["name"], "username": username, "password": password, "schoolid": fid, "cookie": cookie, "signed_in_list": [], "success_sign_num": 0, "sign_task_list": {}}
                        if port == 1:
                            user_list[uid]["main_sign_task"] = asyncio.create_task(connect(session, uid, name, username, password, schoolid, cookie, is_timing, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, _start_time, end_time, address, longitude, latitude, objectid, email))
                        else:
                            user_list[uid]["main_sign_task"] = asyncio.create_task(start_sign(session, uid, name, username, password, schoolid, cookie, is_timing, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, _start_time, end_time, address, longitude, latitude, objectid, email))
                        return True
                    else:
                        return False
                else:
                    return False
            elif not cookie:
                while True:
                    try:
                        async with session.get("https://passport2.chaoxing.com/api/login?name={}&pwd={}&schoolid={}&verify=0".format(student_number, password, schoolid), headers=chaoxing_headers, timeout=10) as resp:
                            status = json.loads(await resp.text())
                        break
                    except Exception as e:
                        logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                if status["result"]:
                    while True:
                        try:
                            async with session.get("https://sso.chaoxing.com/apis/login/userLogin4Uname.do?ft=true", headers=browser_headers, timeout=10) as resp:
                                status2 = json.loads(await resp.text())
                            break
                        except Exception as e:
                            logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                    if status2["result"]:
                        if status2["msg"]["fid"] == 0:
                            fid = ""
                        else:
                            fid = str(status2["msg"]["fid"])
                        user_list[uid] = {"error_num": 0, "port": port, "timestamp": timestamp, "fid": schoolid, "session": session, "imusername": status2["msg"]["accountInfo"]["imAccount"]["username"], "impassword": status2["msg"]["accountInfo"]["imAccount"]["password"], "name": status["realname"], "username": username, "password": password, "schoolid": fid, "cookie": cookie, "signed_in_list": [], "success_sign_num": 0, "sign_task_list": {}}
                        if port == 1:
                            user_list[uid]["main_sign_task"] = asyncio.create_task(connect(session, uid, name, username, password, schoolid, cookie, is_timing, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, _start_time, end_time, address, longitude, latitude, objectid, email))
                        else:
                            user_list[uid]["main_sign_task"] = asyncio.create_task(start_sign(session, uid, name, username, password, schoolid, cookie, is_timing, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, _start_time, end_time, address, longitude, latitude, objectid, email))
                        return True
                    else:
                        return False
                else:
                    return False
            elif cookie:
                while True:
                    try:
                        async with session.get("https://sso.chaoxing.com/apis/login/userLogin4Uname.do?ft=true", headers=browser_headers, cookies=cookie, timeout=10) as resp:
                            status2 = json.loads(await resp.text())
                        break
                    except Exception as e:
                        logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                if status2["result"]:
                    if status2["msg"]["fid"] == 0:
                        fid = ""
                    else:
                        fid = str(status2["msg"]["fid"])
                    user_list[uid] = {"error_num": 0, "port": port, "timestamp": timestamp, "fid": schoolid, "session": session, "imusername": status2["msg"]["accountInfo"]["imAccount"]["username"], "impassword": status2["msg"]["accountInfo"]["imAccount"]["password"], "name": status2["msg"]["name"], "username": username, "password": password, "schoolid": fid, "cookie": cookie, "signed_in_list": [], "success_sign_num": 0, "sign_task_list": {}}
                    if port == 1:
                        user_list[uid]["main_sign_task"] = asyncio.create_task(connect(session, uid, name, username, password, schoolid, cookie, is_timing, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, _start_time, end_time, address, longitude, latitude, objectid, email))
                    else:
                        user_list[uid]["main_sign_task"] = asyncio.create_task(start_sign(session, uid, name, username, password, schoolid, cookie, is_timing, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, _start_time, end_time, address, longitude, latitude, objectid, email))
                    return True
                else:
                    return False
            else:
                return False
        else:
            while True:
                try:
                    async with session.get("https://sso.chaoxing.com/apis/login/userLogin4Uname.do?ft=true", headers=browser_headers, cookies=cookie, timeout=10) as resp:
                        status2 = json.loads(await resp.text())
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            if status2["result"]:
                if status2["msg"]["fid"] == 0:
                    fid = ""
                else:
                    fid = str(status2["msg"]["fid"])
                user_list[uid] = {"error_num": 0, "port": port, "timestamp": timestamp, "fid": schoolid, "session": session, "imusername": status2["msg"]["accountInfo"]["imAccount"]["username"], "impassword": status2["msg"]["accountInfo"]["imAccount"]["password"], "name": status2["msg"]["name"], "username": username, "password": password, "schoolid": fid, "cookie": cookie, "signed_in_list": [], "success_sign_num": 0, "sign_task_list": {}}
                if port == 1:
                    user_list[uid]["main_sign_task"] = asyncio.create_task(connect(session, uid, name, username, password, schoolid, cookie, is_timing, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, _start_time, end_time, address, longitude, latitude, objectid, email))
                else:
                    user_list[uid]["main_sign_task"] = asyncio.create_task(start_sign(session, uid, name, username, password, schoolid, cookie, is_timing, is_numing, is_anti_fishing, is_embezzle, sign_num, info_type, _start_time, end_time, address, longitude, latitude, objectid, email))
                return True
            else:
                return False
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def get_qrcode_for_ws(aid, qrcode_info, address, longitude, latitude):
    try:
        for d in list(qrcode_sign_list.keys()):
            if str(qrcode_sign_list[d]["_aid"]) == aid:
                while True:
                    try:
                        async with qrcode_sign_list[d]["session"].get("https://mobilelearn.chaoxing.com/newsign/signDetail?activePrimaryId="+aid+"&type=1", headers=chaoxing_headers, timeout=10) as resp:
                            res = json.loads(await resp.text())
                        break
                    except Exception as e:
                        logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                if res["status"] == 1:
                    if qrcode_sign_list[d]["address"] != "":
                        address = str(qrcode_sign_list[d]["address"])
                        longitude = str(qrcode_sign_list[d]["longitude"])
                        latitude = str(qrcode_sign_list[d]["latitude"])
                    asyncio.create_task(sign_in_manually_ws(d, qrcode_sign_list[d]["session"], qrcode_sign_list[d]["name"], qrcode_sign_list[d]["username"], qrcode_sign_list[d]["password"], qrcode_sign_list[d]["schoolid"], qrcode_sign_list[d]["cookie"], qrcode_sign_list[d]["courseid"], qrcode_sign_list[d]["classid"], qrcode_sign_list[d]["aid"], qrcode_sign_list[d]["_aid"], qrcode_sign_list[d]["uid"], qrcode_info, address, longitude, latitude, qrcode_sign_list[d]["lesson_name"], qrcode_sign_list[d]["is_numing"], qrcode_sign_list[d]["sign_num"], qrcode_sign_list[d]["email"]))
                else:
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(qrcode_sign_list[d]["uid"]), "name": qrcode_sign_list[d]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"通过微信小程序云端共享获取到课程或班级“"+qrcode_sign_list[d]["lesson_name"]+"”的二维码签到的二维码与指定位置信息，但系统监测到该签到已过期，因此将不再获取该签到活动的签到二维码\n"}), server_key, server_iv)
                    await send_message(sign_server_ws, encrypt)
                    del qrcode_sign_list[d]
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def get_data_base64_decode(_data):
    try:
        base64_decode_str = await asyncio.to_thread(base64.b64decode, _data)
        return base64_decode_str
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def send_message(ws, message):
    while True:
        try:
            if ws.state == 1:
                try:
                    await ws.send(message)
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                    break
            else:
                break
        except Exception as e:
            logging.error(str(e.__traceback__.tb_lineno)+str(e))


async def send_wechat_message(uid, message):
    try:
        encrypt = await get_data_aes_encode(json.dumps({"type": "send_wechat", "uid": uid, "message": message}), server_key, server_iv)
        await send_message(sign_server_ws, encrypt)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


if __name__ == "__main__":
    asyncio.run(sign_server_ws_monitor())
