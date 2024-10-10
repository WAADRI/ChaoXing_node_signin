import queue
import threading
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
import sys
import time
import urllib.parse
import uuid
import aiohttp
import aiosmtplib
import websockets
import yaml
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad, pad
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


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
    with open(config_path, encoding="utf-8") as file:
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
        if node_name == "":
            logging.warning("节点名称不能为空，请修改配置文件后重新启动节点程序")
            time.sleep(3)
            sys.exit()
else:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logging.warning('未检测到节点配置文件，将会自动在当前路径下生成默认配置文件，请稍后自行修改配置文件后再次运行本程序')
    time.sleep(3)
    with open(config_path, "w", encoding="utf-8") as file:
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
  port: 465
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
version = 1.7
user_list = {}
try:
    res = requests.get("https://api.waadri.top/ChaoXing/api/get_version.json", timeout=10).json()
    latest_version = res["latest_version"]
    if latest_version == str(version):
        logging.info("当前节点程序已为最新版本")
    else:
        logging.warning("节点程序检测到新版本，更新内容如下，请在浏览器中访问“"+res["py_download_url"]+"”下载新版本并替换当前版本使用\n"+res["new_version_log"])
        time.sleep(3)
except:
    logging.warning("网络连接异常，版本更新检查失败")
    time.sleep(3)


# 发送邮件
async def send_email(text, uid, result):
    try:
        if email_address != "" and user_list[uid]["bind_email"]:
            # 给邮件末尾添加官方网站的提示，可根据自己需求修改
            text += "<p style=\"text-indent:2em;\">[官方网站] <a href=\"https://cx.waadri.top/\">https://cx.waadri.top/</a></p>"
            # 邮件格式为html格式
            msg = MIMEText(text, 'html', 'utf-8')
            # 发送人
            msg['From'] = formataddr((email_user, email_address))
            # 接收人
            msg['To'] = formataddr(("", user_list[uid]["email"]))
            msg['Subject'] = result
            server = aiosmtplib.SMTP(hostname=email_host, port=email_port, use_tls=email_use_tls)
            await server.connect()
            await server.login(email_address, email_password)
            await server.sendmail(email_address, user_list[uid]["email"], msg.as_string())
            await server.quit()
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 签到监控异常停止处理
async def stop_reason(num, uid, name):
    try:
        # 根据返回不同的num匹配不同的监控异常停止类型
        if num == 1:
            reason = '学习通账号登录失败'
        elif num == 2:
            reason = '课程和班级列表获取失败'
        elif num == 3:
            reason = '全部签到接口均失效'
        else:
            reason = '未知原因'
        event_time2 = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
        logging.info(name+"：由于"+reason+"停止签到")
        await send_email("<p>[学习通在线自动签到系统监控异常停止通知]</p><p style=\"text-indent:2em;\">[异常停止时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[异常停止原因] "+reason+"</p><p style=\"text-indent:2em;\">如需重新启动签到监控请重新登录学习通在线自动签到系统并重新启动签到监控。</p>", uid, "学习通在线自动签到系统监控异常停止通知")
        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"签到异常停止，停止原因为"+reason+"\n"}), server_key, server_iv)
        await send_message(encrypt)
        # 如果不是因为签到列表获取接口由于频繁导致的异常停止则说明用户登录过期，清除掉用户的登录状态，否则仅将用户的签到监控停止
        if num != 3:
            encrypt = await get_data_aes_encode(json.dumps({"type": "user_logout", "uid": uid, "name": name}), server_key, server_iv)
            await send_message(encrypt)
        else:
            encrypt = await get_data_aes_encode(json.dumps({"result": 1, "type": "stop_sign", "uid": uid, "name": name}), server_key, server_iv)
            await send_message(encrypt)
        # 将用户签到信息从节点用户数据列表中移除
        await remove_sign_info(uid)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 接口2监控函数
async def interface_two(uid, courseid, classid, na):
    try:
        if 2 in user_list[uid]["port"]:
            while True:
                try:
                    url = "https://mobilelearn.chaoxing.com/ppt/activeAPI/taskactivelist?courseId="+str(courseid)+"&classId="+str(classid)+"&uid="+str(uid)
                    async with user_list[uid]["session"].get(url, headers=chaoxing_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        # 有时候接口会502，502就重新请求
                        if resp.status == 502:
                            continue
                        _res = json.loads(await resp.text())
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            if _res['result']:
                # 请求成功将接口频繁次数置0
                user_list[uid]["error_num"] = 0
                for i in range(len(_res['activeList'])):
                    # 判断是否为签到活动，活动是否进行中，活动发布时长是否超过24小时
                    if _res['activeList'][i]['activeType'] == 2 and _res['activeList'][i]['status'] == 1 and _res['activeList'][i]["startTime"]/1000+86400 > int(time.time()):
                        aid = _res['activeList'][i]['id']
                        # 如果活动id不在已监控到的活动列表中则进行签到
                        if str(aid) not in user_list[uid]["signed_in_list"]:
                            # 将活动id插入已监控到的活动列表中
                            user_list[uid]["signed_in_list"].append(str(aid))
                            # 如果用户设置的自动签到类型和当前活动类型符合则进行签到
                            if await check_sign_type(uid, str(aid)):
                                user_list[uid]["sign_task_list"][str(aid)] = asyncio.create_task(signt(uid, courseid, classid, aid, _res['activeList'][i]['nameOne'], na, 2))
            # 登录过期处理
            elif _res['errorMsg'] == "请登录后再试":
                asyncio.create_task(stop_reason(1, uid, user_list[uid]["name"]))
                return 1
            # 频繁监控导致接口被封禁处理
            else:
                # 次数小于2，说明当前课程只有1个接口频繁了
                if user_list[uid]["error_num"] < 2:
                    event_time2 = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
                    asyncio.create_task(send_email("<p>[学习通在线自动签到系统签到接口切换通知]</p><p style=\"text-indent:2em;\">[接口切换时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[原签到接口] 接口2（APP端接口）</p><p style=\"text-indent:2em;\">[新签到接口] 接口3（网页端接口）</p><p style=\"text-indent:2em;\">[接口切换原因] 原接口返回提示“"+_res["errorMsg"]+"”</p><p style=\"text-indent:2em;\">[对应课程或班级] "+na+"</p>", uid, "学习通在线自动签到系统签到接口切换通知"))
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"在使用接口2（APP端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+_res["errorMsg"]+"”，系统将尝试使用接口3（网页端接口）进行签到监控\n"}), server_key, server_iv)
                    await send_message(encrypt)
                    # 更换接口
                    user_list[uid]["port"].remove(2)
                    user_list[uid]["port"].append(3)
                    encrypt = await get_data_aes_encode(json.dumps({"type": "change_port", "uid": str(uid), "name": user_list[uid]["name"], "previous_port": 2, "now_port": 3}), server_key, server_iv)
                    await send_message(encrypt)
                    # 接口频繁次数加1
                    user_list[uid]["error_num"] += 1
                    return await interface_three(uid, courseid, classid, na)
                # 次数大于等于2，说明当前课程两个接口都频繁了
                else:
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"在使用接口2（APP端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+_res["errorMsg"]+"”，接口2和接口3均被封禁，请尝试使用接口1（IM协议实时接口）进行签到监控或等待一小时后再尝试使用接口2和接口3进行签到监控\n"}), server_key, server_iv)
                    await send_message(encrypt)
                    user_list[uid]["error_num"] = 0
                    # 如果没有使用接口1则停止监控，否则仅停止非接口1的监控函数
                    if 1 not in user_list[uid]["port"]:
                        asyncio.create_task(stop_reason(3, uid, user_list[uid]["name"]))
                    return 1
        else:
            return await interface_three(uid, courseid, classid, na)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 接口3监控函数
async def interface_three(uid, courseid, classid, na):
    try:
        if 2 not in user_list[uid]["port"]:
            if str(user_list[uid]["schoolid"]) == "":
                fid = "0"
            else:
                fid = str(user_list[uid]["schoolid"])
            while True:
                try:
                    url = "https://mobilelearn.chaoxing.com/v2/apis/active/student/activelist?fid="+fid+"&courseId="+str(courseid)+"&classId="+str(classid)+"&showNotStartedActive=0&_="+str(int(time.time()*1000))
                    async with user_list[uid]["session"].get(url, headers=chaoxing_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 502:
                            continue
                        if str(resp.url) == url:
                            _res = json.loads(await resp.text())
                        else:
                            asyncio.create_task(stop_reason(1, uid, user_list[uid]["name"]))
                            return 1
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            if _res['result']:
                user_list[uid]["error_num"] = 0
                for _data in _res['data']['activeList']:
                    if _data['activeType'] == 2 and _data['status'] == 1 and _data["startTime"]/1000+86400 > int(time.time()):
                        aid = _data['id']
                        if str(aid) not in user_list[uid]["signed_in_list"]:
                            user_list[uid]["signed_in_list"].append(str(aid))
                            if await check_sign_type(uid, str(aid)):
                                user_list[uid]["sign_task_list"][str(aid)] = asyncio.create_task(signt(uid, courseid, classid, aid, _data['nameOne'], na, 3))
            else:
                if user_list[uid]["error_num"] < 2:
                    event_time2 = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
                    asyncio.create_task(send_email("<p>[学习通在线自动签到系统签到接口切换通知]</p><p style=\"text-indent:2em;\">[接口切换时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[原签到接口] 接口3（网页端接口）</p><p style=\"text-indent:2em;\">[新签到接口] 接口2（APP接口）</p><p style=\"text-indent:2em;\">[接口切换原因] 原接口返回提示“"+_res["errorMsg"]+"”</p><p style=\"text-indent:2em;\">[对应课程或班级] "+na+"</p>", uid, "学习通在线自动签到系统签到接口切换通知"))
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"在使用接口3（网页端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+_res["errorMsg"]+"”，系统将尝试使用接口2（APP接口）进行签到监控\n"}), server_key, server_iv)
                    await send_message(encrypt)
                    user_list[uid]["port"].remove(3)
                    user_list[uid]["port"].append(2)
                    encrypt = await get_data_aes_encode(json.dumps({"type": "change_port", "uid": str(uid), "name": user_list[uid]["name"], "previous_port": 3, "now_port": 2}), server_key, server_iv)
                    await send_message(encrypt)
                    user_list[uid]["error_num"] += 1
                    return await interface_two(uid, courseid, classid, na)
                else:
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"在使用接口3（网页端接口）监测课程或班级“"+na+"”的签到活动时页面提示“"+_res["errorMsg"]+"”，接口2和接口3均被封禁，请尝试使用接口1（IM协议实时接口）进行签到监控或等待一小时后再尝试使用接口2和接口3进行签到监控\n"}), server_key, server_iv)
                    await send_message(encrypt)
                    user_list[uid]["error_num"] = 0
                    if 1 not in user_list[uid]["port"]:
                        asyncio.create_task(stop_reason(3, uid, user_list[uid]["name"]))
                    return 1
        else:
            return await interface_two(uid, courseid, classid, na)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 签到函数
async def signt(uid, course_id, class_id, aid, name_one, na, port):
    try:
        if port != 1:
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"课程或班级“"+na+"”监测到签到活动，签到活动名称为“"+name_one+"”\n"}), server_key, server_iv)
            await send_message(encrypt)
        while True:
            try:
                panduanurl = 'https://mobilelearn.chaoxing.com/v2/apis/active/getPPTActiveInfo?activeId='+str(aid)
                async with user_list[uid]["session"].get(panduanurl, headers=browser_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    _res = json.loads(await resp.text())
                if not _res["result"]:
                    asyncio.create_task(stop_reason(1, uid, user_list[uid]["name"]))
                    return 1
                break
            except Exception as e:
                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
        # 获取教师开启滑块验证码的状态
        ifNeedVCode = _res["data"]["ifNeedVCode"]
        # 判断是否开启了多班发放，开启之后仅使用多班发放aid列表中的第一个aid进行签到
        if "multiClassesActives" in _res['data'].keys():
            _aid = _res['data']["multiClassesActives"][0]["aid"]
            _class_id = _res['data']["multiClassesActives"][0]["cid"]
        else:
            _aid = aid
            _class_id = class_id
        start_time = _res["data"]["starttimeStr"]
        # 判断教师是否启用了手动结束签到
        if not _res["data"]["manual"]:
            end_time = _res["data"]["endtimeStr"]
            timelong = str(_res["data"]["day"])+"天"+str(_res["data"]["hour"])+"小时"+str(_res["data"]["minute"])+"分钟"
        else:
            end_time = "无"
            timelong = "教师手动结束签到"
        event_time2 = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
        # 二维码签到
        if _res['data']['otherId'] == 2:
            # 有刷新且指定了签到地点的二维码签到
            if _res['data']['ifrefreshewm'] == 1 and _res['data']['ifopenAddress'] == 1:
                sign_type = str(_res['data']['ewmRefreshTime'])+"秒自动更新且指定了签到地点的二维码签到"
                asyncio.create_task(send_email("<p>[学习通在线自动签到系统二维码签到扫码通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[对应课程或班级] "+na+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+name_one+"</p><p style=\"text-indent:2em;\">[签到类型] "+str(_res['data']['ewmRefreshTime'])+"秒自动更新且指定了签到地点的二维码签到</p><p style=\"text-indent:2em;\">[签到开始时间] "+start_time+"</p><p style=\"text-indent:2em;\">[签到结束时间] "+end_time+"</p><p style=\"text-indent:2em;\">[签到持续时间] "+timelong+"</p><p style=\"text-indent:2em;\">[扫码小程序使用教程] <a href=\"https://api.waadri.top/ChaoXing/MSIT.php\">小程序使用教程点这里</a></p><p style=\"text-indent:2em;\">[签到状态] 第三方签到节点不支持自动获取指定位置信息，等待使用微信小程序“WAADRI的扫码工具”选择指定位置并扫描学习通签到二维码来完成自动签到</p><p style=\"text-indent:2em;\">微信小程序二维码：</p><img src=\"https://www.waadri.top/source/gh_3c371f2be720_1280.jpg\" style=\"width: 100%;height: auto;max-width: 200px;max-height: auto;\">", uid, "学习通二维码签到通知"))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为"+str(_res['data']['ewmRefreshTime'])+"秒自动更新且指定了签到地点的二维码签到，第三方签到节点不支持自动获取指定位置信息，请使用微信小程序“WAADRI的扫码工具”选择指定位置并扫描学习通签到二维码来完成自动签到，小程序使用教程见https://api.waadri.top/ChaoXing/MSIT.php\n"}), server_key, server_iv)
                await send_message(encrypt)
            # 有刷新且未指定签到地点的二维码签到
            elif _res['data']['ifrefreshewm'] == 1:
                sign_type = str(_res['data']['ewmRefreshTime'])+"秒自动更新且未指定签到地点的二维码签到"
                asyncio.create_task(send_email("<p>[学习通在线自动签到系统二维码签到扫码通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[对应课程或班级] "+na+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+name_one+"</p><p style=\"text-indent:2em;\">[签到类型] "+str(_res['data']['ewmRefreshTime'])+"秒自动更新且未指定签到地点的二维码签到</p><p style=\"text-indent:2em;\">[签到开始时间] "+start_time+"</p><p style=\"text-indent:2em;\">[签到结束时间] "+end_time+"</p><p style=\"text-indent:2em;\">[签到持续时间] "+timelong+"</p><p style=\"text-indent:2em;\">[扫码小程序使用教程] <a href=\"https://api.waadri.top/ChaoXing/MSIT.php\">小程序使用教程点这里</a></p><p style=\"text-indent:2em;\">[小程序扫码后签到二维码远程获取链接] <a href=\"https://cx.waadri.top/get_qrcode?activeId="+str(_aid)+"\">点这里远程获取签到二维码</a></p><p style=\"text-indent:2em;\">[签到状态] 等待使用微信小程序“WAADRI的扫码工具”扫描学习通签到二维码来完成自动签到</p><p style=\"text-indent:2em;\">微信小程序二维码：</p><img src=\"https://www.waadri.top/source/gh_3c371f2be720_1280.jpg\" style=\"width: 100%;height: auto;max-width: 200px;max-height: auto;\">", uid, "学习通二维码签到扫码通知"))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为"+str(_res['data']['ewmRefreshTime'])+"秒自动更新且未指定签到地点的二维码签到，请使用微信小程序“WAADRI的扫码工具”扫描学习通签到二维码来完成自动签到，小程序使用教程见https://api.waadri.top/ChaoXing/MSIT.php\n"}), server_key, server_iv)
                await send_message(encrypt)
            # 无刷新且指定了签到地点的二维码签到
            elif _res['data']['ifopenAddress'] == 1:
                sign_type = "无自动更新且指定了签到地点的二维码签到"
                asyncio.create_task(send_email("<p>[学习通在线自动签到系统二维码签到扫码通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[对应课程或班级] "+na+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+name_one+"</p><p style=\"text-indent:2em;\">[签到类型] 无自动更新且指定了签到地点的二维码签到</p><p style=\"text-indent:2em;\">[签到开始时间] "+start_time+"</p><p style=\"text-indent:2em;\">[签到结束时间] "+end_time+"</p><p style=\"text-indent:2em;\">[签到持续时间] "+timelong+"</p><p style=\"text-indent:2em;\">[扫码小程序使用教程] <a href=\"https://api.waadri.top/ChaoXing/MSIT.php\">小程序使用教程点这里</a></p><p style=\"text-indent:2em;\">[签到状态] 第三方签到节点不支持自动获取指定位置信息，等待使用微信小程序“WAADRI的扫码工具”选择指定位置并扫描学习通签到二维码来完成自动签到</p><p style=\"text-indent:2em;\">微信小程序二维码：</p><img src=\"https://www.waadri.top/source/gh_3c371f2be720_1280.jpg\" style=\"width: 100%;height: auto;max-width: 200px;max-height: auto;\">", uid, "学习通二维码签到通知"))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为无自动更新且指定了签到地点的二维码签到，第三方签到节点不支持自动获取指定位置信息，请使用微信小程序“WAADRI的扫码工具”选择指定位置并扫描学习通签到二维码来完成自动签到，小程序使用教程见https://api.waadri.top/ChaoXing/MSIT.php\n"}), server_key, server_iv)
                await send_message(encrypt)
            # 无刷新且未指定签到地点的二维码签到
            else:
                sign_type = "无自动更新且未指定签到地点的二维码签到"
                asyncio.create_task(send_email("<p>[学习通在线自动签到系统二维码签到扫码通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[对应课程或班级] "+na+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+name_one+"</p><p style=\"text-indent:2em;\">[签到类型] 无自动更新且未指定签到地点的二维码签到</p><p style=\"text-indent:2em;\">[签到开始时间] "+start_time+"</p><p style=\"text-indent:2em;\">[签到结束时间] "+end_time+"</p><p style=\"text-indent:2em;\">[签到持续时间] "+timelong+"</p><p style=\"text-indent:2em;\">[扫码小程序使用教程] <a href=\"https://api.waadri.top/ChaoXing/MSIT.php\">小程序使用教程点这里</a></p><p style=\"text-indent:2em;\">[小程序扫码后签到二维码远程获取链接] <a href=\"https://cx.waadri.top/get_qrcode?activeId="+str(_aid)+"\">点这里远程获取签到二维码</a></p><p style=\"text-indent:2em;\">[签到状态] 等待使用微信小程序“WAADRI的扫码工具”扫描学习通签到二维码来完成自动签到</p><p style=\"text-indent:2em;\">微信小程序二维码：</p><img src=\"https://www.waadri.top/source/gh_3c371f2be720_1280.jpg\" style=\"width: 100%;height: auto;max-width: 200px;max-height: auto;\">", uid, "学习通二维码签到扫码通知"))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为无自动更新且未指定签到地点的二维码签到，请使用微信小程序“WAADRI的扫码工具”扫描学习通签到二维码来完成自动签到，小程序使用教程见https://api.waadri.top/ChaoXing/MSIT.php\n"}), server_key, server_iv)
                await send_message(encrypt)
            # 将信息插入二维码待签字典中，等待用户扫码后服务器转发签到二维码解析内容
            temp_data = {"name": user_list[uid]["name"], "aid": str(aid), "_aid": str(_aid), "uid": uid, "lesson_name": na, "event_time2": event_time2, "name_one": name_one, "sign_type": sign_type, "start_time": start_time, "end_time": end_time, "timelong": timelong}
            qrcode_sign_list[str(uid)+str(aid)] = temp_data
            _data = {"type": "get_qrcode", "qrcode_sign_list": [str(_aid)]}
            _data = await get_data_aes_encode(json.dumps(_data), server_key, server_iv)
            await send_message(_data)
            del user_list[uid]["sign_task_list"][str(aid)]
        # 非二维码签到
        else:
            url = "https://mobilelearn.chaoxing.com/pptSign/stuSignajax"
            if str(user_list[uid]["schoolid"]) == "":
                fid = "0"
            else:
                fid = str(user_list[uid]["schoolid"])
            # 所有签到类型都需要提交的参数
            sign_data = {
                "activeId": aid,
                "uid": uid,
                "clientip": "",
                "latitude": "-1",
                "longitude": "-1",
                "appType": "15",
                "fid": fid,
                "name": user_list[uid]["name"]
            }
            # 用来存放邮件或微信通知中需要补充的内容
            other_append_text = ""
            # 普通或拍照签到
            if _res['data']['otherId'] == 0:
                # 拍照签到
                if _res['data']['ifphoto'] == 1:
                    if user_list[uid]["set_objectId"]:
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为拍照签到\n"}), server_key, server_iv)
                        await send_message(encrypt)
                    else:
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为拍照签到，但您未设置拍照图片，将使用普通签到模式执行无拍照图片自动签到\n"}), server_key, server_iv)
                        await send_message(encrypt)
                        other_append_text = "未设置拍照图片，使用普通签到模式执行无拍照图片"
                    sign_type = "拍照签到"
                    sign_data["useragent"] = ""
                    sign_data["objectId"] = user_list[uid]["objectId"]
                    sign_data["validate"] = ""
                # 普通签到
                else:
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为普通签到\n"}), server_key, server_iv)
                    await send_message(encrypt)
                    sign_type = "普通签到"
                    sign_data["useragent"] = ""
            # 手势签到
            elif _res['data']['otherId'] == 3:
                asyncio.create_task(send_email("<p>[学习通在线自动签到系统手势签到通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[对应课程或班级] "+na+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+name_one+"</p><p style=\"text-indent:2em;\">[签到类型] 手势签到</p><p style=\"text-indent:2em;\">[签到开始时间] "+start_time+"</p><p style=\"text-indent:2em;\">[签到结束时间] "+end_time+"</p><p style=\"text-indent:2em;\">[签到持续时间] "+timelong+"</p><p style=\"text-indent:2em;\">[签到状态] 第三方签到节点不支持自动获取手势码，请使用官方节点进行签到或自行登录学习通APP进行签到</p>", uid, "学习通手势签到通知"))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为手势签到，第三方签到节点不支持自动获取手势码，请使用官方节点进行签到或自行登录学习通APP进行签到\n"}), server_key, server_iv)
                await send_message(encrypt)
                del user_list[uid]["sign_task_list"][str(aid)]
                return
            # 位置签到
            elif _res['data']['otherId'] == 4:
                # 指定位置签到
                if _res['data']['ifopenAddress'] == 1:
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为指定了签到地点的位置签到，第三方签到节点不支持自动获取指定位置信息，将使用您预先设置的位置信息进行签到\n"}), server_key, server_iv)
                    await send_message(encrypt)
                    sign_type = "指定位置签到"
                    sign_data["latitude"] = user_list[uid]["latitude"]
                    sign_data["longitude"] = user_list[uid]["longitude"]
                    sign_data["address"] = user_list[uid]["address"]
                    sign_data["ifTiJiao"] = "1"
                    sign_data["validate"] = ""
                    sign_data["vpProbability"] = 0
                    sign_data["vpStrategy"] = ""
                # 普通位置签到
                else:
                    if user_list[uid]["set_address"]:
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为普通位置签到\n"}), server_key, server_iv)
                        await send_message(encrypt)
                    else:
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为普通位置签到，但您未设置位置信息，将使用普通签到模式执行无位置信息自动签到\n"}), server_key, server_iv)
                        await send_message(encrypt)
                        other_append_text = "未设置位置信息，使用普通签到模式执行无位置信息"
                    sign_type = "普通位置签到"
                    sign_data["latitude"] = user_list[uid]["latitude"]
                    sign_data["longitude"] = user_list[uid]["longitude"]
                    sign_data["address"] = user_list[uid]["address"]
                    sign_data["ifTiJiao"] = "1"
                    sign_data["validate"] = ""
                    sign_data["vpProbability"] = 0
                    sign_data["vpStrategy"] = ""
            # 签到码签到
            elif _res['data']['otherId'] == 5:
                asyncio.create_task(send_email("<p>[学习通在线自动签到系统签到码签到通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[对应课程或班级] "+na+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+name_one+"</p><p style=\"text-indent:2em;\">[签到类型] 签到码签到</p><p style=\"text-indent:2em;\">[签到开始时间] "+start_time+"</p><p style=\"text-indent:2em;\">[签到结束时间] "+end_time+"</p><p style=\"text-indent:2em;\">[签到持续时间] "+timelong+"</p><p style=\"text-indent:2em;\">[签到状态] 第三方签到节点不支持自动获取签到码，请使用官方节点进行签到或自行登录学习通APP进行签到</p>", uid, "学习通签到码签到通知"))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到为签到码签到，第三方签到节点不支持自动获取签到码，请使用官方节点进行签到或自行登录学习通APP进行签到\n"}), server_key, server_iv)
                await send_message(encrypt)
                del user_list[uid]["sign_task_list"][str(aid)]
                return
            # 如果是接口1监控到的签到则等待9秒后进行签到防止秒签
            if port == 1:
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"等待9秒后开始检测滑块验证码\n"}), server_key, server_iv)
                await send_message(encrypt)
                await asyncio.sleep(9)
            while True:
                try:
                    preSignurl = "https://mobilelearn.chaoxing.com/newsign/preSign?courseId="+str(course_id)+"&classId="+str(class_id)+"&activePrimaryId="+str(aid)+"&general=1&sys=1&ls=1&appType=15&&uid="+str(uid)+"&tid="+str(user_list[uid]["tid"])+"&ut=s"
                    await user_list[uid]["session"].get(preSignurl, headers=chaoxing_headers, timeout=aiohttp.ClientTimeout(total=10))
                    # 存在滑块验证码
                    if ifNeedVCode:
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到检测到滑块验证码，尝试通过验证\n"}), server_key, server_iv)
                        await send_message(encrypt)
                        async with user_list[uid]["session"].get("https://api.waadri.top/ChaoXing/api/get_captcha", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            res = await resp.json()
                        if res["status"] == 200:
                            sign_data["validate"] = res["validate"]
                            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"滑块验证已通过，开始进行预签到\n"}), server_key, server_iv)
                            await send_message(encrypt)
                        else:
                            asyncio.create_task(send_email("<p>[学习通在线自动签到系统签到失败通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[对应课程或班级] "+na+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+name_one+"</p><p style=\"text-indent:2em;\">[签到类型] "+sign_type+"</p><p style=\"text-indent:2em;\">[签到开始时间] "+start_time+"</p><p style=\"text-indent:2em;\">[签到结束时间] "+end_time+"</p><p style=\"text-indent:2em;\">[签到持续时间] "+timelong+"</p><p style=\"text-indent:2em;\">[签到状态] 签到失败，签到存在滑块验证码且无法通过验证，请使用官方节点进行签到或自行登录学习通APP进行签到</p>", uid, "学习通"+sign_type+"结果：签到失败"))
                            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"自动签到失败，签到存在滑块验证码且无法通过验证，请使用官方节点进行签到或自行登录学习通APP进行签到\n"}), server_key, server_iv)
                            await send_message(encrypt)
                            del user_list[uid]["sign_task_list"][str(aid)]
                            return
                    # 无滑块验证码
                    else:
                        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"该签到未检测到滑块验证码，将直接进行签到\n"}), server_key, server_iv)
                        await send_message(encrypt)
                    async with user_list[uid]["session"].get("https://mobilelearn.chaoxing.com/pptSign/analysis?vs=1&DB_STRATEGY=RANDOM&aid="+str(aid), headers=chaoxing_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        test_res = await resp.text()
                    md5_pattern = re.compile(r'[a-f0-9]{32}')
                    _hash = md5_pattern.findall(test_res)[0]
                    await user_list[uid]["session"].get("https://mobilelearn.chaoxing.com/pptSign/analysis2?DB_STRATEGY=RANDOM&code="+str(_hash), headers=chaoxing_headers, timeout=aiohttp.ClientTimeout(total=10))
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"预签到请求成功，等待1秒后开始签到\n"}), server_key, server_iv)
                    await send_message(encrypt)
                    await asyncio.sleep(1)
                    async with user_list[uid]["session"].get(url, headers=chaoxing_headers, params=sign_data, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        text = await resp.text()
                    if text == "validate":
                        continue
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            # 登录过期
            if text == "请先登录再进行签到":
                asyncio.create_task(stop_reason(1, uid, user_list[uid]["name"]))
                return 1
            # 签到成功
            if text == "success":
                user_list[uid]["success_sign_num"] += 1
                asyncio.create_task(send_email("<p>[学习通在线自动签到系统签到成功通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[对应课程或班级] "+na+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+name_one+"</p><p style=\"text-indent:2em;\">[签到类型] "+sign_type+"</p><p style=\"text-indent:2em;\">[签到开始时间] "+start_time+"</p><p style=\"text-indent:2em;\">[签到结束时间] "+end_time+"</p><p style=\"text-indent:2em;\">[签到持续时间] "+timelong+"</p><p style=\"text-indent:2em;\">[签到状态] "+other_append_text+"签到成功</p>", uid, "学习通"+sign_type+"结果：签到成功"))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"自动签到成功\n"}), server_key, server_iv)
                await send_message(encrypt)
                # 完成了定次签到模式所指定的签到完成次数则停止监控
                if user_list[uid]["is_numing"] and user_list[uid]["success_sign_num"] >= user_list[uid]["sign_num"]:
                    event_time2 = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"定次签到模式已完成指定成功签到次数\n"}), server_key, server_iv)
                    await send_message(encrypt)
                    await send_email("<p>[学习通在线自动签到系统停止监控通知]</p><p style=\"text-indent:2em;\">[监控停止时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[监控停止原因] 定次签到模式完成指定成功签到次数</p><p style=\"text-indent:2em;\">如需重新启动签到监控请登录学习通在线自动签到系统并重新启动签到监控。</p>", uid, "学习通在线自动签到系统停止监控通知")
                    encrypt = await get_data_aes_encode(json.dumps({"result": 1, "type": "need_stop_sign", "uid": uid, "name": user_list[uid]["name"]}), server_key, server_iv)
                    await send_message(encrypt)
            # 签到结束
            elif text == "success2":
                asyncio.create_task(send_email("<p>[学习通在线自动签到系统签到失败通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[对应课程或班级] "+na+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+name_one+"</p><p style=\"text-indent:2em;\">[签到类型] "+sign_type+"</p><p style=\"text-indent:2em;\">[签到开始时间] "+start_time+"</p><p style=\"text-indent:2em;\">[签到结束时间] "+end_time+"</p><p style=\"text-indent:2em;\">[签到持续时间] "+timelong+"</p><p style=\"text-indent:2em;\">[签到状态] "+other_append_text+"签到失败，签到已结束</p>", uid, "学习通"+sign_type+"结果：签到失败"))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"自动签到失败，失败原因为“签到已结束”\n"}), server_key, server_iv)
                await send_message(encrypt)
            # 签到失败
            else:
                asyncio.create_task(send_email("<p>[学习通在线自动签到系统签到失败通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[对应课程或班级] "+na+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+name_one+"</p><p style=\"text-indent:2em;\">[签到类型] "+sign_type+"</p><p style=\"text-indent:2em;\">[签到开始时间] "+start_time+"</p><p style=\"text-indent:2em;\">[签到结束时间] "+end_time+"</p><p style=\"text-indent:2em;\">[签到持续时间] "+timelong+"</p><p style=\"text-indent:2em;\">[签到状态] "+other_append_text+"签到失败，"+text+"</p>", uid, "学习通"+sign_type+"结果：签到失败"))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"自动签到失败，失败原因为“"+text+"”\n"}), server_key, server_iv)
                await send_message(encrypt)
            del user_list[uid]["sign_task_list"][str(aid)]
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# md5加密函数
async def get_data_md5(_data):
    try:
        md5_digest = md5(_data)
        return md5_digest.hexdigest()
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# base64编码函数
async def get_data_base64_encode(_data):
    try:
        base64_encode_str = base64.b64encode(_data)
        return base64_encode_str
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# base64解码函数
async def get_data_aes_decode(_data, _key, _iv):
    try:
        if _data is None:
            return ""
        encrypted = await get_data_base64_decode(_data)
        cipher = AES.new(bytes(_key, "utf-8"), AES.MODE_CBC, bytes(_iv, "utf-8"))
        decrypted = cipher.decrypt(encrypted)
        return unpad(decrypted, AES.block_size).decode()
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))
        return ""


# AES加密函数
async def get_data_aes_encode(_data, _key, tiv):
    try:
        raw = bytes(_data, "utf-8")
        raw = pad(raw, AES.block_size)
        cipher = AES.new(bytes(_key, "utf-8"), AES.MODE_CBC, bytes(tiv, "utf-8"))
        encrypted = cipher.encrypt(raw)
        return (await get_data_base64_encode(encrypted)).decode()
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 服务运行主函数
async def sign_server_ws_monitor():
    global sign_server_ws, qrcode_sign_ws_get_heartbeat_message_time
    # 创建每周日中午12时为所有使用密码登录的用户自动重新登录更新cookie的任务，与主函数同时运行
    asyncio.create_task(user_relogin_loop())
    # 创建每隔12小时为所有非密码登录的用户更新cookie的任务，与主函数同时运行
    asyncio.create_task(get_new_cookie_loop())
    while True:
        try:
            async with websockets.connect("wss://cx.waadri.top/ws/othernode_server/websocket", ping_interval=10) as sign_server_ws:
                t = int(time.time())
                temp_list = []
                # 每次上线将二维码待签字典中所有活动id发给服务器获取对应的签到二维码
                for d in qrcode_sign_list.keys():
                    temp_list.append(qrcode_sign_list[d]["aid"])
                encrypt = await get_data_aes_encode(node_name, server_key, server_iv)
                # 每次上线均需提交的节点数据
                _data = {"t": t, "device_id": encrypt, "uuid": node_uuid, "qrcode_sign_list": temp_list, "password": node_password, "version": version}
                encrypt = await get_data_aes_encode(json.dumps(_data), server_key, server_iv)
                await send_message(encrypt)
                while True:
                    message = await sign_server_ws.recv()
                    # 收到消息则说明连接正常，更新心跳时间戳
                    qrcode_sign_ws_get_heartbeat_message_time = time.time()
                    # 上线成功
                    if message == "success":
                        if node_password == "":
                            node_password_text = "无"
                        else:
                            node_password_text = node_password
                        logging.info("节点上线成功，节点名称："+node_name+"，节点uuid："+node_uuid+"，节点密码："+node_password_text+"，可在在线自动签到系统中使用本节点")
                    # 上线失败，节点名称重复
                    elif message == "duplicate_name":
                        logging.warning("您的节点名称与当前其它已接入系统的节点名称存在重复，请在配置文件中修改节点名称后重新启动本程序")
                        await sign_server_ws.close()
                        time.sleep(3)
                        sys.exit()
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
                            # 收到启动签到监控命令
                            if _data["type"] == "start_sign":
                                if _data["uid"] not in list(user_list.keys()):
                                    result = await person_sign(_data["uid"], _data["username"], _data["student_number"], _data["password"], _data["schoolid"], _data["cookie"], _data["port"], _data["sign_type"], _data["is_timing"], _data["is_numing"], _data["sign_num"], _data["daterange"], _data["set_address"], _data["address"], _data["longitude"], _data["latitude"], _data["set_objectId"], _data["objectId"], _data["bind_email"], _data["email"])
                                    if result:
                                        logging.info(_data["name"]+"启动签到监控")
                                        encrypt = await get_data_aes_encode(json.dumps({"result": 1, "status": _data["is_timing"], "type": "start_sign", "uid": str(_data["uid"]), "port": _data["port"], "node_uuid": node_uuid, "name": _data["name"], "username": _data["username"], "student_number": _data["student_number"], "password": _data["password"], "schoolid": _data["schoolid"], "cookie": _data["cookie"], "sign_type": _data["sign_type"], "is_timing": _data["is_timing"], "is_numing": _data["is_numing"], "sign_num": _data["sign_num"], "daterange": _data["daterange"]}), server_key, server_iv)
                                        await send_message(encrypt)
                                    else:
                                        await stop_reason(1, str(_data["uid"]), user_list[str(_data["uid"])]["name"])
                                        encrypt = await get_data_aes_encode(json.dumps({"result": 0, "type": "start_sign", "uid": str(_data["uid"]), "name": _data["name"], "node_uuid": node_uuid}), server_key, server_iv)
                                        await send_message(encrypt)
                                else:
                                    encrypt = await get_data_aes_encode(json.dumps({"result": 1, "status": user_list[_data["uid"]]["is_timing"], "type": "start_sign", "uid": str(_data["uid"]), "port": user_list[_data["uid"]]["port"], "node_uuid": node_uuid, "name": user_list[_data["uid"]]["name"], "username": user_list[_data["uid"]]["username"], "student_number": user_list[_data["uid"]]["student_number"], "password": user_list[_data["uid"]]["password"], "schoolid": user_list[_data["uid"]]["schoolid"], "cookie": user_list[_data["uid"]]["cookie"], "is_timing": user_list[_data["uid"]]["is_timing"], "is_numing": user_list[_data["uid"]]["is_numing"], "sign_num": user_list[_data["uid"]]["sign_num"], "daterange": user_list[_data["uid"]]["daterange"]}), server_key, server_iv)
                                    await send_message(encrypt)
                            # 首次上线启动所有下发账号的签到监控命令
                            elif _data["type"] == "online_start_sign":
                                diff = list(set(user_list.keys()).difference(set(_data["uid_list"])))
                                if diff:
                                    for u in diff:
                                        logging.info(user_list[u]["name"]+"停止签到监控")
                                        await remove_sign_info(u)
                                diff = list(set(_data["uid_list"]).difference(set(user_list.keys())))
                                if diff:
                                    for u in diff:
                                        for ll in _data["sign_list"]:
                                            if u == ll["uid"]:
                                                result = await person_sign(ll["uid"], ll["username"], ll["student_number"], ll["password"], ll["schoolid"], ll["cookie"], ll["port"], ll["sign_type"], ll["is_timing"], ll["is_numing"], ll["sign_num"], ll["daterange"], ll["set_address"], ll["address"], ll["longitude"], ll["latitude"], ll["set_objectId"], ll["objectId"], ll["bind_email"], ll["email"])
                                                if result:
                                                    logging.info(ll["name"]+"启动签到监控")
                                                    encrypt = await get_data_aes_encode(json.dumps({"result": 1, "status": ll["is_timing"], "type": "online_start_sign", "uid": str(ll["uid"]), "port": ll["port"], "node": "1", "name": ll["name"], "username": ll["username"], "student_number": ll["student_number"], "password": ll["password"], "schoolid": ll["schoolid"], "cookie": ll["cookie"], "is_timing": ll["is_timing"], "is_numing": ll["is_numing"], "sign_num": ll["sign_num"], "daterange": ll["daterange"]}), server_key, server_iv)
                                                    await send_message(encrypt)
                                                else:
                                                    await stop_reason(1, str(ll["uid"]), user_list[str(ll["uid"])]["name"])
                                                    encrypt = await get_data_aes_encode(json.dumps({"result": 0, "type": "start_sign", "uid": str(ll["uid"]), "name": ll["name"], "node": "1"}), server_key, server_iv)
                                                    await send_message(encrypt)
                            # 停止签到监控命令
                            elif _data["type"] == "stop_sign":
                                await remove_sign_info(_data["uid"])
                                encrypt = await get_data_aes_encode(json.dumps({"result": 1, "type": "stop_sign", "uid": _data["uid"], "name": _data["name"]}), server_key, server_iv)
                                await send_message(encrypt)
                            # 强制停止签到监控命令，一般用于节点延迟较大导致启动签到监控命令超时收到则要被强制停止签到监控
                            elif _data["type"] == "force_stop_sign":
                                await remove_sign_info(_data["uid"])
                                encrypt = await get_data_aes_encode(json.dumps({"result": 1, "type": "force_stop_sign", "uid": _data["uid"], "name": _data["name"]}), server_key, server_iv)
                                await send_message(encrypt)
                            # 二维码签到命令
                            elif _data["type"] == "push_qrcode_info":
                                asyncio.create_task(get_qrcode_for_ws(_data["aid"], _data["qrcode_info"], _data["address"], _data["longitude"], _data["latitude"]))
        except websockets.ConnectionClosed:
            logging.warning("节点掉线，尝试重新上线...")
            await asyncio.sleep(1)
        except Exception as e:
            logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            logging.warning("节点掉线，尝试重新上线...")
            await asyncio.sleep(1)


# 与主服务器连接超时判断函数
async def check_sign_ws_heartbeat_message_time(ws):
    try:
        while True:
            if sign_server_ws == ws:
                # 判断上次心跳时间戳与当前时间戳差值是否超过20秒，超过则断开重连
                if time.time() > qrcode_sign_ws_get_heartbeat_message_time+20:
                    if sign_server_ws.state == 1:
                        await sign_server_ws.close()
                    break
                await asyncio.sleep(1)
            else:
                break
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# url解码函数
async def get_data_url_unquote(_data):
    try:
        url_unquote_str = urllib.parse.unquote(_data)
        return url_unquote_str
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# url编码函数
async def get_data_url_quote(_data):
    try:
        url_quote_str = urllib.parse.quote(_data)
        return url_quote_str
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 服务器下发签到二维码后二维码签到函数
async def sign_in_manually_ws(session, keys, name, schoolid, _aid, uid, qrcode_info, address, longitude, latitude, lesson_name, is_numing, sign_num, event_time2, name_one, sign_type, _start_time, end_time, timelong, message_list):
    try:
        # 提取enc
        enc_decode = await get_data_url_unquote(qrcode_info)
        enc_txt = enc_decode[enc_decode.find("&enc=")+5:]
        enc_code = enc_txt[:enc_txt.find("&")]
        # 组装位置信息参数并进行url编码
        location = await get_data_url_quote('{"result":1,"latitude":'+latitude+',"longitude":'+longitude+',"address":"'+address+'"}')
        url = "https://mobilelearn.chaoxing.com/pptSign/stuSignajax?enc="+str(enc_code)+"&name="+str(name)+"&activeId="+str(_aid)+"&uid="+str(uid)+"&clientip=&location="+location+"&latitude=-1&longitude=-1&fid="+str(schoolid)+"&appType=15&deviceCode=&vpProbability=0&vpStrategy="
        while True:
            try:
                await session.get(qrcode_info, headers=chaoxing_headers, timeout=aiohttp.ClientTimeout(total=10))
                async with session.get(url, headers=chaoxing_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    txt = await resp.text()
                # 登录过期
                if txt == "请先登录再进行签到":
                    del qrcode_sign_list[keys]
                    await stop_reason(1, uid, user_list[uid]["name"])
                    return
                elif "validate" in txt:
                    enc2 = txt.replace("validate_", "")
                    async with session.get("https://mobilelearn.chaoxing.com/widget/sign/pcStuSignController/checkIfValidate?DB_STRATEGY=PRIMARY_KEY&STRATEGY_PARA=activeId&activeId="+str(_aid)+"&puid=", headers=browser_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        validate_text = json.loads(await resp.text())
                    # 需要滑块验证码
                    if validate_text["result"]:
                        async with session.get("https://api.waadri.top/ChaoXing/api/get_captcha", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            res = await resp.json()
                        if res["status"] == 200:
                            url = "https://mobilelearn.chaoxing.com/pptSign/stuSignajax?enc="+str(enc_code)+"&name="+str(name)+"&activeId="+str(_aid)+"&uid="+str(uid)+"&clientip=&location="+location+"&latitude=-1&longitude=-1&fid="+str(schoolid)+"&appType=15&deviceCode=&vpProbability=0&vpStrategy=&enc2="+enc2+"&validate="+res["validate"]
                        else:
                            tasks = []
                            del qrcode_sign_list[keys]
                            tasks.append(asyncio.create_task(send_email("<p>[学习通在线自动签到系统签到失败通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[对应课程或班级] "+lesson_name+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+name_one+"</p><p style=\"text-indent:2em;\">[签到类型] "+sign_type+"</p><p style=\"text-indent:2em;\">[签到开始时间] "+_start_time+"</p><p style=\"text-indent:2em;\">[签到结束时间] "+end_time+"</p><p style=\"text-indent:2em;\">[签到持续时间] "+timelong+"</p><p style=\"text-indent:2em;\">[签到状态] 签到失败，签到存在滑块验证码且无法通过验证，系统将不再获取该签到活动的签到二维码来为您签到，请使用官方节点进行签到或自行登录学习通APP进行签到</p>", uid, "学习通二维码签到结果：签到失败")))
                            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但自动签到失败，签到存在滑块验证码且无法通过验证，系统将不再获取该签到活动的签到二维码来为您签到，请使用官方节点进行签到或自行登录学习通APP进行签到\n"}), server_key, server_iv)
                            message_list.put(encrypt)
                            await asyncio.gather(*tasks)
                            return
                    async with session.get("https://mobilelearn.chaoxing.com/pptSign/analysis?vs=1&DB_STRATEGY=RANDOM&aid="+str(_aid), headers=chaoxing_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        test_res = await resp.text()
                    md5_pattern = re.compile(r'[a-f0-9]{32}')
                    _hash = md5_pattern.findall(test_res)[0]
                    await session.get("https://mobilelearn.chaoxing.com/pptSign/analysis2?DB_STRATEGY=RANDOM&code="+str(_hash), headers=chaoxing_headers, timeout=aiohttp.ClientTimeout(total=10))
                    await asyncio.sleep(1)
                    async with session.get(url, headers=chaoxing_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        txt = await resp.text()
                    if "validate" in txt:
                        continue
                    break
                else:
                    break
            except Exception as e:
                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
        tasks = []
        # 签到成功
        if txt == "success":
            del qrcode_sign_list[keys]
            tasks.append(asyncio.create_task(send_email("<p>[学习通在线自动签到系统二维码签到成功通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[对应课程或班级] "+lesson_name+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+name_one+"</p><p style=\"text-indent:2em;\">[签到类型] "+sign_type+"</p><p style=\"text-indent:2em;\">[签到开始时间] "+_start_time+"</p><p style=\"text-indent:2em;\">[签到结束时间] "+end_time+"</p><p style=\"text-indent:2em;\">[签到持续时间] "+timelong+"</p><p style=\"text-indent:2em;\">[签到状态] 通过微信小程序云端共享获取到签到二维码，签到成功</p>", uid, "二维码签到结果：签到成功")))
            user_list[str(uid)]["success_sign_num"] += 1
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，自动签到成功\n"}), server_key, server_iv)
            message_list.put(encrypt)
            # 完成了定次签到模式所指定的签到完成次数则停止监控
            if is_numing and user_list[uid]["success_sign_num"] >= sign_num:
                tasks.append(asyncio.create_task(send_email("<p>[学习通在线自动签到系统停止监控通知]</p><p style=\"text-indent:2em;\">[监控停止时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[监控停止原因] 定次签到模式完成指定成功签到次数</p><p style=\"text-indent:2em;\">如需重新启动签到监控请登录学习通在线自动签到系统并重新启动签到监控。</p>", uid, "学习通在线自动签到系统停止监控通知")))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"定次签到模式已完成指定成功签到次数\n"}), server_key, server_iv)
                message_list.put(encrypt)
                encrypt = await get_data_aes_encode(json.dumps({"result": 1, "type": "need_stop_sign", "uid": uid, "name": name}), server_key, server_iv)
                message_list.put(encrypt)
            await asyncio.gather(*tasks)
        # 签到结束
        elif txt == "success2":
            del qrcode_sign_list[keys]
            tasks.append(asyncio.create_task(send_email("<p>[学习通在线自动签到系统二维码签到失败通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[对应课程或班级] "+lesson_name+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+name_one+"</p><p style=\"text-indent:2em;\">[签到类型] "+sign_type+"</p><p style=\"text-indent:2em;\">[签到开始时间] "+_start_time+"</p><p style=\"text-indent:2em;\">[签到结束时间] "+end_time+"</p><p style=\"text-indent:2em;\">[签到持续时间] "+timelong+"</p><p style=\"text-indent:2em;\">[签到状态] 签到失败，签到已结束，将不再获取该签到活动的签到二维码来为您签到</p>", uid, "学习通二维码签到结果：签到失败")))
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但学习通提示“签到已结束”，系统将不再获取该签到活动的签到二维码来为您签到\n"}), server_key, server_iv)
            message_list.put(encrypt)
            await asyncio.gather(*tasks)
        # 已签到过了，将签到信息从二维码待签字典中移除，不再签到
        elif txt == "您已签到过了":
            del qrcode_sign_list[keys]
            tasks.append(asyncio.create_task(send_email("<p>[学习通在线自动签到系统二维码签到失败通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[对应课程或班级] "+lesson_name+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+name_one+"</p><p style=\"text-indent:2em;\">[签到类型] "+sign_type+"</p><p style=\"text-indent:2em;\">[签到开始时间] "+_start_time+"</p><p style=\"text-indent:2em;\">[签到结束时间] "+end_time+"</p><p style=\"text-indent:2em;\">[签到持续时间] "+timelong+"</p><p style=\"text-indent:2em;\">[签到状态] 签到失败，您已签到过了，将不再获取该签到活动的签到二维码来为您签到</p>", uid, "二维码签到结果：签到失败")))
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但学习通提示“您已签到过了”，系统将不再获取该签到活动的签到二维码来为您签到\n"}), server_key, server_iv)
            message_list.put(encrypt)
            await asyncio.gather(*tasks)
        else:
            # 位置信息有偏差，不在教师指定签到位置范围内
            if txt == "errorLocation1" or txt == "errorLocation2":
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但自动签到失败，失败原因为“"+str(txt)+"”，您所选位置可能不在教师指定签到位置范围内，请使用微信小程序重新选择指定位置并扫描未过期的签到二维码，扫描后系统将继续尝试为您签到\n"}), server_key, server_iv)
                message_list.put(encrypt)
            # 其它失败，如二维码过期
            else:
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": name, "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"通过微信小程序云端共享获取到课程或班级“"+lesson_name+"”的二维码签到的二维码与指定位置信息，但自动签到失败，失败原因为“"+str(txt)+"”，签到二维码可能已过期，请使用微信小程序重新扫描未过期的签到二维码，扫描后系统将继续尝试为您签到\n"}), server_key, server_iv)
                message_list.put(encrypt)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 查找并提取签到消息
async def get_message(ws, message, uid):
    try:
        chatid = await getchatid(message)
        if chatid is None:
            return
        sessonend = 11
        while True:
            index = sessonend
            if chr(message[index]) != b"\x22".decode():
                index += 1
                break
            else:
                index += 1
            sessonend = message[index]+(message[index+1]-1)*0x80+index+2
            index += 2
            if sessonend < 0 or chr(message[index]).encode() != b"\x08":
                index += 1
                break
            else:
                index += 1
            temp = await get_data_base64_encode(await buildreleasesession(chatid, message[index:index+9]))
            await ws.send("[\""+temp.decode("utf-8")+"\"]")
            index += 10
            att = await getattachment(message, index, sessonend)
            if att is not None:
                # 判断是否为签到
                if att["attachmentType"] == 15 and "atype" in att["att_chat_course"].keys() and (att["att_chat_course"]["atype"] == 2 or att["att_chat_course"]["atype"] == 0) and att["att_chat_course"]["type"] == 1 and att["att_chat_course"]["aid"] != 0:
                    # 判断是否存在已监控到的活动列表中，否的话插入列表并签到
                    if str(att["att_chat_course"]["aid"]) not in user_list[uid]["signed_in_list"]:
                        user_list[uid]["signed_in_list"].append(str(att["att_chat_course"]["aid"]))
                        # 判断是否为课程或班级签到
                        if "mobilelearn.chaoxing.com/newsign/preSign" in att["att_chat_course"]["url"]:
                            # 如果用户设置的自动签到类型和当前活动类型符合则进行签到
                            if await check_sign_type(uid, str(att["att_chat_course"]["aid"])):
                                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"收到来自课程或班级“"+att["att_chat_course"]["courseInfo"]["coursename"]+"”的签到活动，签到活动名称为“"+att["att_chat_course"]["title"]+"”\n"}), server_key, server_iv)
                                await send_message(encrypt)
                                user_list[uid]["sign_task_list"][str(att["att_chat_course"]["aid"])] = asyncio.create_task(signt(uid, att["att_chat_course"]["courseInfo"]["courseid"], att["att_chat_course"]["courseInfo"]["classid"], att["att_chat_course"]["aid"], att["att_chat_course"]["title"], att["att_chat_course"]["courseInfo"]["coursename"], 1))
                        # 群聊签到
                        elif att["att_chat_course"]["atype"] == 2 and "7" in user_list[uid]["sign_type"]:
                            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"收到来自群聊的签到活动，签到活动名称为“"+att["att_chat_course"]["title"]+"”\n"}), server_key, server_iv)
                            await send_message(encrypt)
                            user_list[uid]["sign_task_list"][str(att["att_chat_course"]["aid"])] = asyncio.create_task(group_signt(uid, att["att_chat_course"]["aid"], att["att_chat_course"]["title"]))
            break
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 检查活动类型是否符合规则函数
async def check_sign_type(uid, activeid):
    while True:
        try:
            panduanurl = 'https://mobilelearn.chaoxing.com/v2/apis/active/getPPTActiveInfo?activeId='+str(activeid)
            async with user_list[uid]["session"].get(panduanurl, headers=browser_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                _res = json.loads(await resp.text())
            if not _res["result"]:
                asyncio.create_task(stop_reason(1, uid, user_list[uid]["name"]))
                return 1
            break
        except Exception as e:
            logging.debug(str(e.__traceback__.tb_lineno)+str(e))
    if _res['data']['otherId'] == 0:
        if _res['data']['ifphoto'] == 1:
            this_sign_type = "1"
        else:
            this_sign_type = "0"
    elif _res['data']['otherId'] == 2:
        this_sign_type = "2"
    elif _res['data']['otherId'] == 3:
        this_sign_type = "3"
    elif _res['data']['otherId'] == 4:
        if _res['data']['ifopenAddress'] == 1:
            this_sign_type = "6"
        else:
            this_sign_type = "4"
    elif _res['data']['otherId'] == 5:
        this_sign_type = "5"
    else:
        return False
    if this_sign_type in user_list[uid]["sign_type"]:
        return True
    else:
        return False


# 群聊签到函数
async def group_signt(uid, aid, name_one):
    try:
        event_time2 = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"等待10秒后开始自动签到\n"}), server_key, server_iv)
        await send_message(encrypt)
        await asyncio.sleep(10)
        while True:
            try:
                async with user_list[uid]["session"].get("https://mobilelearn.chaoxing.com/sign/stuSignajax?activeId="+str(aid)+"&clientip=&useragent="+await get_data_url_quote(chaoxing_headers["User-Agent"])+"&uid="+str(uid)+"&latitude="+str(user_list[uid]["latitude"])+"&longitude="+str(user_list[uid]["longitude"])+"&address="+str(user_list[uid]["address"])+"&fid="+str(user_list[uid]["schoolid"])+"&objectId="+str(user_list[uid]["objectId"]), headers=chaoxing_headers) as resp:
                    info = await resp.text()
                break
            except Exception as e:
                logging.debug(str(e.__traceback__.tb_lineno) + str(e))
        # 签到成功
        if info == "success":
            user_list[uid]["success_sign_num"] += 1
            asyncio.create_task(send_email("<p>[学习通在线自动签到系统签到成功通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+name_one+"</p><p style=\"text-indent:2em;\">[签到类型] 群聊签到</p><p style=\"text-indent:2em;\">[签到状态] 签到成功</p>", uid, "学习通群聊签到结果：签到成功"))
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"自动签到成功\n"}), server_key, server_iv)
            await send_message(encrypt)
            # 完成了定次签到模式所指定的签到完成次数则停止监控
            if user_list[uid]["is_numing"] and user_list[uid]["success_sign_num"] >= user_list[uid]["sign_num"]:
                event_time2 = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"定次签到模式已完成指定成功签到次数\n"}), server_key, server_iv)
                await send_message(encrypt)
                await send_email("<p>[学习通在线自动签到系统停止监控通知]</p><p style=\"text-indent:2em;\">[监控停止时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[监控停止原因] 定次签到模式完成指定成功签到次数</p><p style=\"text-indent:2em;\">如需重新启动签到监控请登录学习通在线自动签到系统并重新启动签到监控。</p>", uid, "学习通在线自动签到系统停止监控通知")
                encrypt = await get_data_aes_encode(json.dumps({"result": 1, "type": "need_stop_sign", "uid": uid, "name": user_list[uid]["name"]}), server_key, server_iv)
                await send_message(encrypt)
        # 已签到过了
        elif info == "false":
            asyncio.create_task(send_email("<p>[学习通在线自动签到系统签到失败通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+name_one+"</p><p style=\"text-indent:2em;\">[签到类型] 群聊签到</p><p style=\"text-indent:2em;\">[签到状态] 签到失败，您已签到过了</p>", uid, "学习通群聊签到结果：签到失败"))
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"自动签到失败，失败原因为“您已签到过了”\n"}), server_key, server_iv)
            await send_message(encrypt)
        # 其它签到失败
        else:
            asyncio.create_task(send_email("<p>[学习通在线自动签到系统签到失败通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+name_one+"</p><p style=\"text-indent:2em;\">[签到类型] 群聊签到</p><p style=\"text-indent:2em;\">[签到状态] 签到失败，"+info+"</p>", uid, "在线自动签到系统签到结果：签到失败"))
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"自动签到失败，失败原因为“"+info+"”\n"}), server_key, server_iv)
            await send_message(encrypt)
        del user_list[uid]["sign_task_list"][str(aid)]
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 解析IM协议消息函数
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


# 解析IM协议消息函数
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


# 解析IM协议消息函数
async def buildreleasesession(chatid, session):
    try:
        return bytearray([0x08, 0x00, 0x40, 0x00, 0x4a])+chr(len(chatid)+38).encode()+b"\x10"+session+bytearray([0x1a, 0x29, 0x12])+chr(len(chatid)).encode()+chatid.encode("utf-8")+bytesend+bytearray([0x58, 0x00])
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 首次与环信IM连接获取未读消息函数
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


# 获取环信消息ID函数
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


# 解析IM协议消息函数
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


# 根据环信消息ID获取消息详情函数
async def get_taskinfo(ws, message):
    try:
        if await getchatid(message) is None:
            return
        mess2 = message.decode("utf-8")
        temp = ""
        for i in range(len(mess2)):
            if i == 3:
                temp += b"\x00".decode()
            elif i == 6:
                temp += b"\x1a".decode()
            else:
                temp += mess2[i]
        mess2 = temp+bytearray([0x58, 0x00]).decode()
        temp = await get_data_base64_encode(mess2.encode())
        await ws.send("[\""+temp.decode("utf-8")+"\"]")
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 登录环信IM函数
async def login(ws, uid):
    try:
        while True:
            try:
                async with user_list[uid]["session"].post("https://a1-vip6.easemob.com/cx-dev/cxstudy/token", headers=browser_headers, data=json.dumps({"grant_type": "password", "password": user_list[uid]["impassword"], "username": user_list[uid]["imusername"]}), timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    _res = json.loads(await resp.text())
                break
            except Exception as e:
                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
        if "error" not in _res.keys():
            usuid = _res["user"]["username"]
            im_token = _res["access_token"]
            timestamp = str(int(time.time() * 1000))
            temp = await get_data_base64_encode(b"\x08\x00\x12"+chr(52+len(usuid)).encode()+b"\x0a\x0e"+"cx-dev#cxstudy".encode()+b"\x12"+chr(len(usuid)).encode()+usuid.encode()+b"\x1a\x0b"+"easemob.com".encode()+b"\x22\x13"+("webim_"+timestamp).encode()+b"\x1a\x85\x01"+"$t$".encode()+im_token.encode()+b"\x40\x03\x4a\xc0\x01\x08\x10\x12\x05\x33\x2e\x30\x2e\x30\x28\x00\x30\x00\x4a\x0d"+timestamp.encode()+b"\x62\x05\x77\x65\x62\x69\x6d\x6a\x13\x77\x65\x62\x69\x6d\x5f"+timestamp.encode()+b"\x72\x85\x01\x24\x74\x24"+im_token.encode()+b"\x50\x00\x58\x00")
            _data = "[\""+temp.decode()+"\"]"
            await ws.send(_data)
        else:
            asyncio.create_task(stop_reason(1, uid, user_list[uid]["name"]))
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 将用户签到信息从节点用户数据列表中移除函数
async def remove_sign_info(uid):
    try:
        # 查找二维码代签列表中是否存在该用户，有则移除
        for k in list(qrcode_sign_list.keys()):
            if str(uid) == str(qrcode_sign_list[k]["uid"]):
                del qrcode_sign_list[k]
        if uid in user_list.keys():
            # 停止与主服务器连接超时判断函数的运行，否则30秒后会再次与环信IM连接
            if 1 in user_list[uid]["port"] and "ws_sign_heartbeat" in user_list[uid].keys() and not user_list[uid]["ws_sign_heartbeat"].done():
                user_list[uid]["ws_sign_heartbeat"].cancel()
            # 停止所有签到函数的运行
            for s in list(user_list[uid]["sign_task_list"].keys()):
                if not user_list[uid]["sign_task_list"][s].done():
                    user_list[uid]["sign_task_list"][s].cancel()
            # 停止所有接口的签到监控函数运行
            for m in user_list[uid]["main_sign_task"]:
                if not m.done():
                    m.cancel()
            # 关闭用户session会话
            await user_list[uid]["session"].close()
            logging.info(user_list[uid]["name"]+"停止签到监控")
            del user_list[uid]
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 监控开始前监控时间处理函数
async def check_monitor_time(uid):
    # 如果用户启用了定时签到模式则执行监控时间检查函数
    if user_list[uid]["is_timing"]:
        temp_time = []
        for d in user_list[uid]["daterange"]:
            temp_time.append(datetime.datetime.fromtimestamp(d[0]).strftime("%Y-%m-%d %H:%M:%S")+"-"+datetime.datetime.fromtimestamp(d[1]).strftime("%Y-%m-%d %H:%M:%S"))
        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"定时签到模式已启用，系统将在"+"、".join(temp_time)+"启动签到监控\n"}), server_key, server_iv)
        await send_message(encrypt)
        asyncio.create_task(check_sign_time(uid))
    # 未启用定时签到模式则直接根据用户设置接口启动对应的签到监控函数
    else:
        if len(user_list[uid]["port"]) == 2:
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"当前使用双接口进行签到监控\n"}), server_key, server_iv)
            await send_message(encrypt)
        if 1 in user_list[uid]["port"]:
            user_list[uid]["main_sign_task"].append(asyncio.create_task(connect(uid)))
        if 2 in user_list[uid]["port"] or 3 in user_list[uid]["port"]:
            user_list[uid]["main_sign_task"].append(asyncio.create_task(start_sign(uid)))


# 环信IM连接处理主函数
async def connect(uid):
    try:
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
                        # 需要登录
                        if message == "o":
                            await login(ws, uid)
                        # 消息
                        elif message[0] == "a":
                            mess = json.loads(message[1:])[0]
                            mess = await get_data_base64_decode(mess)
                            if len(mess) < 5:
                                return
                            # 有新消息，调用根据环信消息ID获取消息详情函数获取消息详情
                            if mess[:5] == b"\x08\x00\x40\x02\x4a":
                                await get_taskinfo(ws, mess)
                            # 首次与环信IM连接，获取未读消息
                            elif mess[:5] == b"\x08\x00\x40\x01\x4a":
                                await first_get_taskinfo(ws, mess)
                            # 登录成功消息
                            elif mess[:5] == b"\x08\x00@\x03J":
                                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"与学习通服务器的websockets连接成功，正在监听签到活动\n"}), server_key, server_iv)
                                await send_message(encrypt)
                                await ws.send("[\"CABAAVgA\"]")
                            # 获取到消息详情，执行查找并提取签到消息函数
                            else:
                                await get_message(ws, mess, uid)
            except websockets.ConnectionClosed:
                if "ws_sign_heartbeat" in user_list[uid].keys() and not user_list[uid]["ws_sign_heartbeat"].done():
                    user_list[uid]["ws_sign_heartbeat"].cancel()
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"与学习通服务器的websockets连接断开，正在重连……\n"}), server_key, server_iv)
                await send_message(encrypt)
            except Exception as e:
                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                if "ws_sign_heartbeat" in user_list[uid].keys() and not user_list[uid]["ws_sign_heartbeat"].done():
                    user_list[uid]["ws_sign_heartbeat"].cancel()
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"与学习通服务器的websockets连接断开，正在重连……\n"}), server_key, server_iv)
                await send_message(encrypt)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 环信IM心跳时间检查函数
async def check_ws_heartbeat_message_time(ws, uid):
    try:
        while True:
            # 上次心跳时间距当前时间超过60秒则断开连接进行重连
            if time.time() > user_list[uid]["ws_heartbeat_time"]+60:
                if ws.state == 1:
                    await ws.close()
                break
            await asyncio.sleep(1)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 监控时间检查函数
async def check_sign_time(uid):
    try:
        # 双接口监控模式提示
        if len(user_list[uid]["port"]) == 2:
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"当前使用双接口进行签到监控\n"}), server_key, server_iv)
            await send_message(encrypt)
        # 从设置的监控时间范围列表中循环提取监控时间范围
        for d in range(len(user_list[uid]["daterange"])):
            # 判断当前时间戳是否大于当前监控结束时间戳，是则进行下一次循环比较
            if int(time.time()) > user_list[uid]["daterange"][d][1]:
                continue
            # 如果不大于当前监控结束时间戳则判断当前监控开始时间戳是否大于当前时间戳，是则说明当前时间未到监控开始时间，将每隔一秒再次检查
            while user_list[uid]["daterange"][d][0] > int(time.time()):
                # 如果用户uid存在于节点用户数据列表中则说明用户未停止监控，否则退出函数执行
                if uid in user_list.keys():
                    await asyncio.sleep(1)
                else:
                    return
            # 监控开始时间已到，启动签到监控
            if 1 in user_list[uid]["port"]:
                user_list[uid]["main_sign_task"].append(asyncio.create_task(connect(uid)))
            if 2 in user_list[uid]["port"] or 3 in user_list[uid]["port"]:
                user_list[uid]["main_sign_task"].append(asyncio.create_task(start_sign(uid)))
            # 循环检查监控结束时间戳是否大于当前时间戳，是则说明当前时间未到监控结束时间，将每隔一秒再次检查
            while int(time.time()) <= user_list[uid]["daterange"][d][1]:
                # 如果用户uid存在于节点用户数据列表中则说明用户未停止监控，否则退出函数执行
                if uid in user_list.keys():
                    await asyncio.sleep(1)
                else:
                    return
            # 如果当前循环下标不是最长下标则说明还存在下一次循环，停止所有接口的签到监控函数并发送下次启动时间提醒消息
            if d != len(user_list[uid]["daterange"])-1:
                for m in user_list[uid]["main_sign_task"]:
                    if not m.done():
                        m.cancel()
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"定时签到模式所指定本次的监控停止时间已到，签到监控已停止，下次签到监控启动时间为"+datetime.datetime.fromtimestamp(user_list[uid]["daterange"][d+1][0]).strftime("%Y-%m-%d %H:%M:%S")+"\n"}), server_key, server_iv)
                await send_message(encrypt)
        # for循环结束，停止签到监控
        event_time2 = datetime.datetime.strftime(datetime.datetime.now(), '%Y-%m-%d %H:%M:%S')
        await send_email("<p>[学习通在线自动签到系统停止监控通知]</p><p style=\"text-indent:2em;\">[监控停止时间] "+event_time2+"</p><p style=\"text-indent:2em;\">[监控停止原因] 定时签到模式所指定监控停止最晚时间已到</p><p style=\"text-indent:2em;\">如需重新启动签到监控请登录学习通在线自动签到系统并重新启动签到监控。</p>", uid, "学习通在线自动签到系统停止监控通知")
        encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"定时签到模式所指定监控停止时间已到\n"}), server_key, server_iv)
        await send_message(encrypt)
        encrypt = await get_data_aes_encode(json.dumps({"result": 1, "type": "stop_sign", "uid": uid, "name": user_list[uid]["name"]}), server_key, server_iv)
        await send_message(encrypt)
        await remove_sign_info(uid)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 非接口1的循环监控主函数
async def start_sign(uid):
    try:
        user_list[uid]["clazzdata"] = []
        # 获取课程列表1
        while True:
            try:
                async with user_list[uid]["session"].post("https://a1-vip6.easemob.com/cx-dev/cxstudy/token", headers=browser_headers, data=json.dumps({"grant_type": "password", "password": user_list[uid]["impassword"], "username": user_list[uid]["imusername"]}), timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    _res = json.loads(await resp.text())
                break
            except Exception as e:
                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
        # 登录过期
        if "error" in _res.keys():
            await stop_reason(1, uid, user_list[uid]["name"])
            return
        token = _res["access_token"]
        imuid = _res["user"]["username"]
        while True:
            try:
                async with user_list[uid]["session"].get("https://a1-vip6.easemob.com/cx-dev/cxstudy/users/"+imuid+"/joined_chatgroups?detail=true&version=v3&pagenum=1&pagesize=10000", headers={"Authorization": "Bearer "+token, "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.69 Safari/537.36"}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    r = json.loads(await resp.text())
                break
            except Exception as e:
                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
        # 登录过期
        if "error" in r.keys():
            await stop_reason(2, uid, user_list[uid]["name"])
            return
        cdata = r["data"]
        for item in cdata:
            # 判断数据为课程或班级而不是群聊
            if item["description"] != "" and item["description"] != "面对面群聊":
                class_data = json.loads(item["description"])
                # 判断当前用户不为课程教师
                if (item['permission'] == 'member' or item['permission'] == 'admin') and "courseInfo" in class_data.keys():
                    if item["name"] == "":
                        course_name = class_data["courseInfo"]["coursename"]
                    else:
                        course_name = item["name"]
                    pushdata = {"courseid": class_data["courseInfo"]["courseid "], "name": course_name, "classid": class_data["courseInfo"]["classid"]}
                    user_list[uid]["clazzdata"].append(pushdata)
        # 获取课程列表2
        while True:
            try:
                async with user_list[uid]["session"].get("https://mooc1-api.chaoxing.com/mycourse/backclazzdata?view=json&rss=1", headers=browser_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    _res = json.loads(await resp.text())
                break
            except Exception as e:
                logging.debug(str(e.__traceback__.tb_lineno)+str(e))
        if _res["result"]:
            temp_clazzdata = user_list[uid]["clazzdata"]
            for d in _res['channelList']:
                # 判断当前数据为课程且用户为当前课程的学生且当前课程未结束
                if d['cataid'] == '100000002' and d['content']['roletype'] == 3 and d['content']['state'] == 0:
                    is_find = False
                    for _p in temp_clazzdata:
                        if str(_p["courseid"]) == str(d["content"]["course"]["data"][0]["id"]) and str(_p["classid"]) == str(d["content"]["id"]):
                            is_find = True
                            break
                    # 与通过课程列表1获取的数据做比较，若当前课程数据不在课程列表1则插入当前课程数据
                    if not is_find:
                        pushdata = {"courseid": d["content"]["course"]["data"][0]["id"], "name": d["content"]["name"], "classid": d["content"]["id"], "sign_number": 0, "teacherid_list": []}
                        user_list[uid]["clazzdata"].append(pushdata)
        # 登录过期
        else:
            await stop_reason(1, uid, user_list[uid]["name"])
            return
        # 使用接口2进行监控
        if 2 in user_list[uid]["port"]:
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"课程和班级列表获取成功，共获取到"+str(len(user_list[uid]["clazzdata"]))+"条课程和班级数据，签到监控已启动，当前监控接口为接口2（APP端接口）\n"}), server_key, server_iv)
            await send_message(encrypt)
        # 使用接口3进行监控
        else:
            encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(uid), "name": user_list[uid]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"课程和班级列表获取成功，共获取到"+str(len(user_list[uid]["clazzdata"]))+"条课程和班级数据，签到监控已启动，当前监控接口为接口3（网页端接口）\n"}), server_key, server_iv)
            await send_message(encrypt)
        # 循环进行签到监控
        while True:
            for _data in user_list[uid]["clazzdata"]:
                na = _data['name']
                if 2 in user_list[uid]["port"]:
                    rt = await interface_two(uid, _data["courseid"], _data["classid"], na)
                else:
                    rt = await interface_three(uid, _data["courseid"], _data["classid"], na)
                if rt == 1:
                    if 1 not in user_list[uid]["port"]:
                        await user_list[uid]["session"].close()
                    return
            await asyncio.sleep(60)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 启动签到监控命令下发后尝试登录获取cookie和session会话
async def person_sign(uid, username, student_number, password, schoolid, cookie, port, sign_type, is_timing, is_numing, sign_num, daterange, set_address, address, longitude, latitude, set_objectId, objectId, bind_email, email):
    try:
        session = aiohttp.ClientSession()
        # 判断是否为密码登录
        if password != "":
            # 手机号登录
            while True:
                try:
                    async with session.get("https://passport2.chaoxing.com/api/login?name={}&pwd={}&schoolid=&verify=0".format(urllib.parse.quote(username), urllib.parse.quote(password)), headers=browser_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        status = json.loads(await resp.text())
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            if status["result"]:
                while True:
                    try:
                        async with session.get("https://sso.chaoxing.com/apis/login/userLogin4Uname.do?ft=true", headers=browser_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            status2 = json.loads(await resp.text())
                        break
                    except Exception as e:
                        logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                # 登录成功，保存所有数据到节点用户数据列表中并创建任务运行监控开始前监控时间处理函数
                if status2["result"]:
                    if status2["msg"]["fid"] == 0:
                        fid = ""
                    else:
                        fid = str(status2["msg"]["fid"])
                    user_list[uid] = {"error_num": 0, "port": port, "session": session, "imusername": status2["msg"]["accountInfo"]["imAccount"]["username"], "impassword": status2["msg"]["accountInfo"]["imAccount"]["password"], "name": status["realname"], "username": username, "password": password, "student_number": student_number, "schoolid": fid, "tid": str(status2["msg"]["uid"]), "cookie": cookie, "sign_type": sign_type, "is_timing": is_timing, "is_numing": is_numing, "sign_num": sign_num, "daterange": daterange, "set_address": set_address, "address": address, "longitude": longitude, "latitude": latitude, "set_objectId": set_objectId, "objectId": objectId, "bind_email": bind_email, "email": email, "signed_in_list": [], "success_sign_num": 0, "sign_task_list": {}, "main_sign_task": []}
                    user_list[uid]["main_sign_task"].append(asyncio.create_task(check_monitor_time(uid)))
                    return True
                # 密码登录失败，判断是否为cookie登录
                elif cookie:
                    while True:
                        try:
                            async with session.get("https://sso.chaoxing.com/apis/login/userLogin4Uname.do?ft=true", headers=browser_headers, cookies=cookie, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                                status2 = json.loads(await resp.text())
                            break
                        except Exception as e:
                            logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                    # 登录成功，保存所有数据到节点用户数据列表中并创建任务运行监控开始前监控时间处理函数
                    if status2["result"]:
                        if status2["msg"]["fid"] == 0:
                            fid = ""
                        else:
                            fid = str(status2["msg"]["fid"])
                        user_list[uid] = {"error_num": 0, "port": port, "session": session, "imusername": status2["msg"]["accountInfo"]["imAccount"]["username"], "impassword": status2["msg"]["accountInfo"]["imAccount"]["password"], "name": status2["msg"]["name"], "username": username, "password": password, "student_number": student_number, "schoolid": fid, "tid": str(status2["msg"]["uid"]), "cookie": cookie, "sign_type": sign_type, "is_timing": is_timing, "is_numing": is_numing, "sign_num": sign_num, "daterange": daterange, "set_address": set_address, "address": address, "longitude": longitude, "latitude": latitude, "set_objectId": set_objectId, "objectId": objectId, "bind_email": bind_email, "email": email, "signed_in_list": [], "success_sign_num": 0, "sign_task_list": {}, "main_sign_task": []}
                        user_list[uid]["main_sign_task"].append(asyncio.create_task(check_monitor_time(uid)))
                        return True
                    # 密码登录和cookie登录均失败，向主服务器返回登录失败情况
                    else:
                        await session.close()
                        return False
                # 密码登录失败，cookie内容为空，向主服务器返回登录失败情况
                else:
                    await session.close()
                    return False
            # 手机号登录失败，尝试机构账号登录
            elif not cookie:
                while True:
                    try:
                        async with session.get("https://passport2.chaoxing.com/api/login?name={}&pwd={}&schoolid={}&verify=0".format(urllib.parse.quote(student_number), urllib.parse.quote(password), urllib.parse.quote(schoolid)), headers=browser_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            status = json.loads(await resp.text())
                        break
                    except Exception as e:
                        logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                if status["result"]:
                    while True:
                        try:
                            async with session.get("https://sso.chaoxing.com/apis/login/userLogin4Uname.do?ft=true", headers=browser_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                                status2 = json.loads(await resp.text())
                            break
                        except Exception as e:
                            logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                    # 登录成功，保存所有数据到节点用户数据列表中并创建任务运行监控开始前监控时间处理函数
                    if status2["result"]:
                        if status2["msg"]["fid"] == 0:
                            fid = ""
                        else:
                            fid = str(status2["msg"]["fid"])
                        user_list[uid] = {"error_num": 0, "port": port, "session": session, "imusername": status2["msg"]["accountInfo"]["imAccount"]["username"], "impassword": status2["msg"]["accountInfo"]["imAccount"]["password"], "name": status["realname"], "username": username, "password": password, "student_number": student_number, "schoolid": fid, "tid": str(status2["msg"]["uid"]), "cookie": cookie, "sign_type": sign_type, "is_timing": is_timing, "is_numing": is_numing, "sign_num": sign_num, "daterange": daterange, "set_address": set_address, "address": address, "longitude": longitude, "latitude": latitude, "set_objectId": set_objectId, "objectId": objectId, "bind_email": bind_email, "email": email, "signed_in_list": [], "success_sign_num": 0, "sign_task_list": {}, "main_sign_task": []}
                        user_list[uid]["main_sign_task"].append(asyncio.create_task(check_monitor_time(uid)))
                        return True
                    # 密码登录失败，cookie内容为空，向主服务器返回登录失败情况
                    else:
                        await session.close()
                        return False
                # 密码登录失败，cookie内容为空，向主服务器返回登录失败情况
                else:
                    await session.close()
                    return False
            # 密码登录失败，尝试cookie登录
            elif cookie:
                while True:
                    try:
                        async with session.get("https://sso.chaoxing.com/apis/login/userLogin4Uname.do?ft=true", headers=browser_headers, cookies=cookie, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            status2 = json.loads(await resp.text())
                        break
                    except Exception as e:
                        logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                # 登录成功，保存所有数据到节点用户数据列表中并创建任务运行监控开始前监控时间处理函数
                if status2["result"]:
                    if status2["msg"]["fid"] == 0:
                        fid = ""
                    else:
                        fid = str(status2["msg"]["fid"])
                    user_list[uid] = {"error_num": 0, "port": port, "session": session, "imusername": status2["msg"]["accountInfo"]["imAccount"]["username"], "impassword": status2["msg"]["accountInfo"]["imAccount"]["password"], "name": status2["msg"]["name"], "username": username, "password": password, "student_number": student_number, "schoolid": fid, "tid": str(status2["msg"]["uid"]), "cookie": cookie, "sign_type": sign_type, "is_timing": is_timing, "is_numing": is_numing, "sign_num": sign_num, "daterange": daterange, "set_address": set_address, "address": address, "longitude": longitude, "latitude": latitude, "set_objectId": set_objectId, "objectId": objectId, "bind_email": bind_email, "email": email, "signed_in_list": [], "success_sign_num": 0, "sign_task_list": {}, "main_sign_task": []}
                    user_list[uid]["main_sign_task"].append(asyncio.create_task(check_monitor_time(uid)))
                    return True
                # cookie登录失败，向主服务器返回登录失败情况
                else:
                    await session.close()
                    return False
            # 密码登录失败，cookie为空，向主服务器返回登录失败情况
            else:
                await session.close()
                return False
        # 密码为空，尝试cookie登录
        else:
            while True:
                try:
                    async with session.get("https://sso.chaoxing.com/apis/login/userLogin4Uname.do?ft=true", headers=browser_headers, cookies=cookie, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        status2 = json.loads(await resp.text())
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            # 登录成功，保存所有数据到节点用户数据列表中并创建任务运行监控开始前监控时间处理函数
            if status2["result"]:
                if status2["msg"]["fid"] == 0:
                    fid = ""
                else:
                    fid = str(status2["msg"]["fid"])
                user_list[uid] = {"error_num": 0, "port": port, "session": session, "imusername": status2["msg"]["accountInfo"]["imAccount"]["username"], "impassword": status2["msg"]["accountInfo"]["imAccount"]["password"], "name": status2["msg"]["name"], "username": username, "password": password, "student_number": student_number, "schoolid": fid, "tid": str(status2["msg"]["uid"]), "cookie": cookie, "sign_type": sign_type, "is_timing": is_timing, "is_numing": is_numing, "sign_num": sign_num, "daterange": daterange, "set_address": set_address, "address": address, "longitude": longitude, "latitude": latitude, "set_objectId": set_objectId, "objectId": objectId, "bind_email": bind_email, "email": email, "signed_in_list": [], "success_sign_num": 0, "sign_task_list": {}, "main_sign_task": []}
                user_list[uid]["main_sign_task"].append(asyncio.create_task(check_monitor_time(uid)))
                return True
            # cookie登录失败，向主服务器返回登录失败情况
            else:
                await session.close()
                return False
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 异步任务完成等待函数
async def async_task_runner(loop, task_list):
    try:
        asyncio.set_event_loop(loop)
        await asyncio.gather(*task_list)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 创建新线程执行二维码签到函数，避免主线程负载过高运行阻塞影响二维码签到效率
def thread_function(_qrcode_sign_list, aid, qrcode_info, address, longitude, latitude, message_list):
    try:
        loop = asyncio.new_event_loop()
        tasks = []
        # 从二维码待签字典中循环提取并执行二维码签到
        for d in list(_qrcode_sign_list.keys()):
            task = check_qrcode(d, aid, qrcode_info, address, longitude, latitude, user_list[_qrcode_sign_list[d]["uid"]]["session"].cookie_jar, message_list)
            tasks.append(task)
        asyncio.set_event_loop(loop)
        loop.run_until_complete(async_task_runner(loop, tasks))
        loop.close()
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 二维码签到命令处理主函数
async def get_qrcode_for_ws(aid, qrcode_info, address, longitude, latitude):
    try:
        # 创建列表，用来保存要发送的日志信息
        message_list = queue.Queue()
        thread = threading.Thread(target=thread_function, args=(qrcode_sign_list, aid, qrcode_info, address, longitude, latitude, message_list))
        # 启动线程
        thread.start()
        # 等待线程执行完毕
        thread.join()
        queue_size = message_list.qsize()
        # 执行完后提取线程中插入的所有元素并循环发送日志消息
        for _ in range(queue_size):
            item = message_list.get()
            await send_message(item)
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 二维码签到执行函数
async def check_qrcode(d, aid, qrcode_info, address, longitude, latitude, cookie, message_list):
    # 判断传入参数所在字典的键值的aid和参数传入的aid是否相同，相同则说明服务器下发的是这个二维码签到的二维码参数，检查签到条件并执行签到
    if str(qrcode_sign_list[d]["_aid"]) == aid:
        tasks = []
        async with aiohttp.ClientSession(cookie_jar=cookie) as session:
            while True:
                try:
                    if d in qrcode_sign_list.keys():
                        async with session.get("https://mobilelearn.chaoxing.com/newsign/signDetail?activePrimaryId="+aid+"&type=1", headers=chaoxing_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            _res = json.loads(await resp.text())
                    else:
                        return
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            # 判断签到是否过期
            if _res["status"] == 1:
                # 判断签到是否超过24小时
                if (_res["startTime"]["time"] / 1000+86400) < int(time.time()):
                    tasks.append(asyncio.create_task(send_email("<p>[学习通在线自动签到系统二维码签到取消通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+qrcode_sign_list[d]["event_time2"]+"</p><p style=\"text-indent:2em;\">[对应课程或班级] "+qrcode_sign_list[d]["lesson_name"]+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+qrcode_sign_list[d]["name_one"]+"</p><p style=\"text-indent:2em;\">[签到类型] "+qrcode_sign_list[d]["sign_type"]+"</p><p style=\"text-indent:2em;\">[签到开始时间] "+qrcode_sign_list[d]["start_time"]+"</p><p style=\"text-indent:2em;\">[签到结束时间] "+qrcode_sign_list[d]["end_time"]+"</p><p style=\"text-indent:2em;\">[签到持续时间] "+qrcode_sign_list[d]["timelong"]+"</p><p style=\"text-indent:2em;\">[签到状态] 通过微信小程序云端共享获取到签到二维码，但签到发布时长超过24小时，因此取消签到</p>", qrcode_sign_list[d]["uid"], "二维码签到结果：签到取消")))
                    encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(qrcode_sign_list[d]["uid"]), "name": qrcode_sign_list[d]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"通过微信小程序云端共享获取到课程或班级“"+qrcode_sign_list[d]["lesson_name"]+"”的二维码签到的二维码与指定位置信息，但系统监测到该签到发布时长超过24小时，因此取消对当前签到活动进行签到且不再获取该签到活动的签到二维码\n"}), server_key, server_iv)
                    message_list.put(encrypt)
                    await asyncio.gather(*tasks)
                    del qrcode_sign_list[d]
                else:
                    await sign_in_manually_ws(session, d, qrcode_sign_list[d]["name"], user_list[qrcode_sign_list[d]["uid"]]["schoolid"], qrcode_sign_list[d]["_aid"], qrcode_sign_list[d]["uid"], qrcode_info, address, longitude, latitude, qrcode_sign_list[d]["lesson_name"], user_list[qrcode_sign_list[d]["uid"]]["is_numing"], user_list[qrcode_sign_list[d]["uid"]]["sign_num"], qrcode_sign_list[d]["event_time2"], qrcode_sign_list[d]["name_one"], qrcode_sign_list[d]["sign_type"], qrcode_sign_list[d]["start_time"], qrcode_sign_list[d]["end_time"], qrcode_sign_list[d]["timelong"], message_list)
            else:
                tasks.append(asyncio.create_task(send_email("<p>[学习通在线自动签到系统二维码签到取消通知]</p><p style=\"text-indent:2em;\">[签到监测时间] "+qrcode_sign_list[d]["event_time2"]+"</p><p style=\"text-indent:2em;\">[对应课程或班级] "+qrcode_sign_list[d]["lesson_name"]+"</p><p style=\"text-indent:2em;\">[签到活动名称] "+qrcode_sign_list[d]["name_one"]+"</p><p style=\"text-indent:2em;\">[签到类型] "+qrcode_sign_list[d]["sign_type"]+"</p><p style=\"text-indent:2em;\">[签到开始时间] "+qrcode_sign_list[d]["start_time"]+"</p><p style=\"text-indent:2em;\">[签到结束时间] "+qrcode_sign_list[d]["end_time"]+"</p><p style=\"text-indent:2em;\">[签到持续时间] "+qrcode_sign_list[d]["timelong"]+"</p><p style=\"text-indent:2em;\">[签到状态] 通过微信小程序云端共享获取到签到二维码，但签到已结束，因此取消签到</p>", qrcode_sign_list[d]["uid"], "二维码签到结果：签到取消")))
                encrypt = await get_data_aes_encode(json.dumps({"type": "send_sign_message", "uid": str(qrcode_sign_list[d]["uid"]), "name": qrcode_sign_list[d]["name"], "message": datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')+"通过微信小程序云端共享获取到课程或班级“"+qrcode_sign_list[d]["lesson_name"]+"”的二维码签到的二维码与指定位置信息，但系统监测到该签到已过期，因此将不再获取该签到活动的签到二维码\n"}), server_key, server_iv)
                message_list.put(encrypt)
                await asyncio.gather(*tasks)
                del qrcode_sign_list[d]


# base64解码函数
async def get_data_base64_decode(_data):
    try:
        base64_decode_str = base64.b64decode(_data)
        return base64_decode_str
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 密码登录用户循环重新登录更新cookie函数
async def user_relogin_loop():
    while True:
        now = datetime.datetime.now()
        # 如果当前时间是星期天的中午12时0分则循环节点用户数据列表运行重新登录函数
        if now.weekday() == 6 and now.hour == 12 and now.minute == 0:
            try:
                for uid in list(user_list.keys()):
                    await user_relogin(uid)
            except Exception as e:
                logging.error(str(e.__traceback__.tb_lineno)+str(e))
        await asyncio.sleep(60)


# 重新登录函数
async def user_relogin(uid):
    try:
        session = aiohttp.ClientSession()
        if user_list[uid]["password"] != "":
            while True:
                try:
                    async with session.get("https://passport2.chaoxing.com/api/login?name={}&pwd={}&schoolid=&verify=0".format(urllib.parse.quote(user_list[uid]["username"]), urllib.parse.quote(user_list[uid]["password"])), headers=chaoxing_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        status = json.loads(await resp.text())
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            if status["result"]:
                while True:
                    try:
                        async with session.get("https://sso.chaoxing.com/apis/login/userLogin4Uname.do?ft=true", headers=browser_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            status2 = json.loads(await resp.text())
                        break
                    except Exception as e:
                        logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                if status2["result"]:
                    old_session = user_list[uid]["session"]
                    user_list[uid]["session"] = session
                    await old_session.close()
                else:
                    await session.close()
            else:
                while True:
                    try:
                        async with session.get("https://passport2.chaoxing.com/api/login?name={}&pwd={}&schoolid={}&verify=0".format(urllib.parse.quote(user_list[uid]["student_number"]), urllib.parse.quote(user_list[uid]["password"]), urllib.parse.quote(user_list[uid]["schoolid"])), headers=chaoxing_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                            status = json.loads(await resp.text())
                        break
                    except Exception as e:
                        logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                if status["result"]:
                    while True:
                        try:
                            async with session.get("https://sso.chaoxing.com/apis/login/userLogin4Uname.do?ft=true", headers=browser_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                                status2 = json.loads(await resp.text())
                            break
                        except Exception as e:
                            logging.debug(str(e.__traceback__.tb_lineno)+str(e))
                    if status2["result"]:
                        old_session = user_list[uid]["session"]
                        user_list[uid]["session"] = session
                        await old_session.close()
                    else:
                        await session.close()
                else:
                    await session.close()
        else:
            await session.close()
    except Exception as e:
        logging.error(str(e.__traceback__.tb_lineno)+str(e))


# 非密码登录用户循环更新cookie函数
async def get_new_cookie_loop():
    while True:
        # 每12小时循环一次节点用户数据列表并运行更新cookie函数
        await asyncio.sleep(43200)
        for uid in list(user_list.keys()):
            if user_list[uid]["cookie"]:
                await get_new_cookie(uid)


# 更新cookie函数
async def get_new_cookie(uid):
    while True:
        try:
            async with user_list[uid]["session"].get("https://sso.chaoxing.com/apis/login/userLogin4Uname.do?ft=true", headers=browser_headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                status2 = json.loads(await resp.text())
            break
        except Exception as e:
            logging.debug(str(e.__traceback__.tb_lineno)+str(e))
    if status2["result"]:
        user_list[uid]["cookie"] = {cookie.key: cookie.value for cookie in resp.cookies.values()}


# 向主服务器发送消息函数
async def send_message(message):
    while True:
        try:
            # 判断与主服务器连接状态
            if sign_server_ws.state == 1:
                try:
                    await sign_server_ws.send(message)
                    break
                except Exception as e:
                    logging.debug(str(e.__traceback__.tb_lineno)+str(e))
            else:
                await asyncio.sleep(1)
        except Exception as e:
            logging.error(str(e.__traceback__.tb_lineno)+str(e))


if __name__ == "__main__":
    asyncio.run(sign_server_ws_monitor())
