import asyncio
import base64
import datetime
from email.mime.text import MIMEText
from email.utils import formataddr
import logging
import os
import random
import re
import signal
import socket
import sqlite3
import ssl
import sys
import time
import traceback
from urllib.parse import urlparse, parse_qs, quote, unquote
import uuid


class ColoredFormatter(logging.Formatter):
    COLOR_CODES = {
        logging.DEBUG: "\033[94m",
        logging.INFO: "\033[92m",
        logging.WARNING: "\033[93m",
        logging.ERROR: "\033[91m",
        logging.CRITICAL: "\033[1;91m"
    }
    RESET_CODE = "\033[0m"

    def format(self, record):
        msg = super().format(record)
        color_code = self.COLOR_CODES.get(record.levelno, "")
        return f"{color_code}{msg}{self.RESET_CODE}"


LOGGER = logging.getLogger()
LOG_HANDLER = logging.StreamHandler()
LOG_HANDLER.setFormatter(ColoredFormatter("%(asctime)s - %(levelname)s - %(message)s"))
LOGGER.handlers.clear()
LOGGER.addHandler(LOG_HANDLER)
LOGGER.setLevel(logging.INFO)
INSTALL_PACKAGES = ["aiofiles", "aiohttp", "aiosmtplib", "certifi", "orjson", "pycryptodome", "python-dateutil", "pyyaml", "requests", "tenacity", "websockets"]


async def install():
    LOGGER.info("开始安装/更新第三方库")
    cmd = [sys.executable, "-m", "pip", "install"]+INSTALL_PACKAGES+["--no-cache-dir", "--upgrade", "-i", "https://pypi.mirrors.ustc.edu.cn/simple/"]
    process = await asyncio.create_subprocess_exec(*cmd)
    await process.wait()
    if process.returncode != 0:
        cmd = [sys.executable, "-m", "pip", "install"]+INSTALL_PACKAGES+["--no-cache-dir", "--upgrade", "-i", "https://pypi.mirrors.ustc.edu.cn/simple/", "--break-system-packages"]
        process = await asyncio.create_subprocess_exec(*cmd)
        await process.wait()
    LOGGER.info("第三方库安装/更新完成，即将自动重启程序")
    os.execl(sys.executable, sys.executable, os.path.abspath(__file__))


try:
    import aiofiles
    import aiohttp
    import aiosmtplib
    import certifi
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad, pad
    from dateutil import parser
    import orjson
    import requests
    from tenacity import retry, wait_fixed
    import websockets
    from websockets.protocol import State
    import yaml
except ImportError:
    asyncio.run(install())
except Exception:
    LOGGER.error(traceback.format_exc())
    sys.exit(1)


APP = {}
REALPATH = os.getcwd()
SERVER_KEY = "h8WQ0NiQHPSOIDL8YgsohndEBfEuuRqt"
SERVER_IV = "A3NyHTbzQEhrZHqc"
QRCODE_SIGN_DICT = {}
BYTESEND = bytearray([0x1A, 0x16, 0x63, 0x6F, 0x6E, 0x66, 0x65, 0x72, 0x65, 0x6E, 0x63, 0x65, 0x2E, 0x65, 0x61, 0x73, 0x65, 0x6D, 0x6F, 0x62, 0x2E, 0x63, 0x6F, 0x6D])
BYTESATTACHMENT = bytearray([0x0a, 0x61, 0x74, 0x74, 0x61, 0x63, 0x68, 0x6D, 0x65, 0x6E, 0x74, 0x10, 0x08, 0x32])
BROWSER_HEADER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/86.0.4240.198 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest"
}
NODE_VERSION = 3.7
USER_LIST = {}
BACKGROUND_TASKS = set()
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.load_verify_locations(certifi.where())
SIGN_INFO_DICT = {"code": {}, "location": {}, "validate": {}, "fail_msg": {}}
LOCATION_LOCK = asyncio.Lock()
CODE_LOCK = asyncio.Lock()
VALIDATE_LOCK = asyncio.Lock()
MSG_SEND_LOCK = asyncio.Lock()
SQL_LOCK = asyncio.Lock()
NODE_CONFIG = {"email": {"address": "", "password": "", "use_tls": True, "host": "", "port": 465, "user": ""}, "node": {"name": "", "password": "", "limit": 0}, "show_frequently": True, "night_monitor": True, "debug": False, "uuid": ""}
NODE_STRAT_TIME = int(time.time())
BASE_TIMEOUT = aiohttp.ClientTimeout(total=10)
sign_server_ws: websockets.ClientConnection = None
UN_NOTICE_USER_LIST = []
offline_hour = random.randint(0, 5)
offline_minute = random.randint(0, 59)


async def json_encode(data):
    return orjson.dumps(data).decode()


async def json_decode(data):
    return orjson.loads(data.encode())


@retry(wait=wait_fixed(2))
async def get_request(uid: str, name: str, session: aiohttp.ClientSession, url: str, params: dict = None, header: dict = None, cookie: dict = None, json_type: bool = True, need_cookie: bool = False, ignore_status_code: bool = False, need_response: bool = False, need_status_code: bool = False) -> dict[str, dict | str | list[dict]] | str:
    try:
        if not header:
            header = BROWSER_HEADER
        async with session.get(url, params=params, headers=header, cookies=cookie, allow_redirects=True, timeout=BASE_TIMEOUT) as resp:
            text = await resp.text()
        if not ignore_status_code:
            if resp.ok:
                if json_type:
                    json_data = await json_decode(text)
                    if need_cookie:
                        json_data["sign_cookie"] = {key: value.value for key, value in resp.cookies.items()}
                    if need_status_code:
                        json_data["status_code"] = resp.status
                    return json_data
                else:
                    return text
            elif resp.status == 403:
                LOGGER.error("检测到当前节点IP疑似被学习通拉黑导致无法继续监控，请更换当前节点IP后再尝试运行节点程序进行监控")
                await asyncio.sleep(3)
                for d in list(USER_LIST):
                    await remove_sign_info(d, USER_LIST[d]["name"])
                await APP["SIGN_ERROR_LOG"].close()
                await APP["SIGN_DEBUG_LOG"].close()
                await APP["CX_SESSION"].close()
                sys.exit()
            elif resp.status == 500:
                if json_type:
                    return {"result": 1, "activeList": [], "data": {"activeList": [], "array": []}, "errorMsg": None, "status_code": 500}
                else:
                    await record_debug_log(resp.url.__str__(), False)
                    await record_debug_log(text, False)
                    await record_debug_log(f"{uid}-{name}:请求{url}时出现非2XX响应", False)
                    return resp.raise_for_status()
            elif need_status_code:
                json_data = await json_decode(text)
                json_data["status_code"] = resp.status
                return json_data
            else:
                await record_debug_log(resp.url.__str__(), False)
                await record_debug_log(text, False)
                await record_debug_log(f"{uid}-{name}:请求{url}时出现非2XX响应", False)
                return resp.raise_for_status()
        else:
            if resp.status == 502:
                return resp.raise_for_status()
            elif json_type:
                try:
                    return await json_decode(text)
                except orjson.JSONDecodeError:
                    await record_error_log(resp.status.__str__())
                    await record_error_log(text)
                    await record_error_log(traceback.format_exc())
                    if not need_response:
                        return {"result": 0, "errorMsg": "登录已过期，请重新登录"}
                    else:
                        return {"result": 0, "status": 0, "errorMsg": text}
            else:
                return text
    except aiohttp.client_exceptions.ClientConnectorError as e:
        await record_debug_log(f"{uid}-{name}:请求{url}时出现aiohttp.client_exceptions.ClientConnectorError", False)
        raise e
    except asyncio.exceptions.TimeoutError as e:
        await record_debug_log(f"{uid}-{name}:请求{url}时出现asyncio.exceptions.TimeoutError", False)
        raise e
    except aiohttp.client_exceptions.ClientConnectionError as e:
        await record_debug_log(f"{uid}-{name}:请求{url}时出现aiohttp.client_exceptions.ClientConnectionError", False)
        raise e
    except aiohttp.client_exceptions.ClientOSError as e:
        await record_debug_log(f"{uid}-{name}:请求{url}时出现aiohttp.client_exceptions.ClientOSError", False)
        raise e
    except aiohttp.client_exceptions.ClientPayloadError as e:
        await record_debug_log(f"{uid}-{name}:请求{url}时出现aiohttp.client_exceptions.ClientPayloadError", False)
        raise e
    except aiohttp.client_exceptions.TooManyRedirects:
        await record_error_log(traceback.format_exc())
        LOGGER.error("检测到当前节点IP疑似被学习通拉黑导致无法继续监控，请更换当前节点IP后再尝试运行节点程序进行监控")
        await asyncio.sleep(3)
        for d in list(USER_LIST):
            await remove_sign_info(d, USER_LIST[d]["name"])
        await APP["SIGN_ERROR_LOG"].close()
        await APP["SIGN_DEBUG_LOG"].close()
        await APP["CX_SESSION"].close()
        sys.exit()
    except RuntimeError as e:
        if "Session is closed" in e.args:
            await record_debug_log(f"{uid}-{name}:请求{url}时出现RuntimeError，停止请求", False)
            return {"result": 0, "status": 0}
        else:
            raise e
    except aiohttp.client_exceptions.ClientResponseError as e:
        if e.status == 502:
            raise e
        else:
            await record_error_log(traceback.format_exc())
            raise e
    except Exception as e:
        await record_error_log(traceback.format_exc())
        raise e


@retry(wait=wait_fixed(2))
async def post_request(uid: str, name: str, session: aiohttp.ClientSession, url: str, json_data: dict = None, need_status_code: bool = False) -> dict[str, dict | str | int]:
    try:
        async with session.post(url, json=json_data, headers=BROWSER_HEADER, timeout=BASE_TIMEOUT) as resp:
            text = await resp.text()
        if not need_status_code:
            if resp.ok:
                return await json_decode(text)
            else:
                await record_debug_log(f"{uid}-{name}:请求{url}时出现非2XX响应", False)
                return resp.raise_for_status()
        else:
            json_data = await json_decode(text)
            json_data["status_code"] = resp.status
            return json_data
    except aiohttp.client_exceptions.ClientConnectorError as e:
        await record_debug_log(f"{uid}-{name}:请求{url}时出现aiohttp.client_exceptions.ClientConnectorError", False)
        raise e
    except aiohttp.client_exceptions.ClientOSError as e:
        await record_debug_log(f"{uid}-{name}:请求{url}时出现aiohttp.client_exceptions.ClientOSError", False)
        raise e
    except asyncio.exceptions.TimeoutError as e:
        await record_debug_log(f"{uid}-{name}:请求{url}时出现asyncio.exceptions.TimeoutError", False)
        raise e
    except aiohttp.client_exceptions.ServerDisconnectedError as e:
        await record_debug_log(f"{uid}-{name}:请求{url}时出现aiohttp.client_exceptions.ServerDisconnectedError", False)
        raise e
    except RuntimeError as e:
        if "Session is closed" in e.args:
            await record_debug_log(f"{uid}-{name}:请求{url}时出现RuntimeError，停止请求", False)
            return {"result": 0, "status_code": 400}
        else:
            raise e
    except Exception as e:
        await record_error_log(traceback.format_exc())
        raise e


async def cx_get_request(url: str, json_type: bool = True):
    async with APP["CX_SESSION"].get(url, timeout=BASE_TIMEOUT) as resp:
        if resp.ok:
            if json_type:
                return await json_decode(await resp.text())
            else:
                return await resp.read()
        else:
            await record_debug_log(resp.url.__str__(), False)
            await record_debug_log(await resp.text(), False)
            await record_debug_log(f"请求{url}时出现非2XX响应", False)
            return resp.raise_for_status()


async def record_error_log(txt, msg_type=True):
    if msg_type:
        LOGGER.debug(txt)
    else:
        LOGGER.error(txt)
    try:
        await APP["SIGN_ERROR_LOG"].write(f"{datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S] ')}{txt}\n")
        await APP["SIGN_ERROR_LOG"].flush()
    except Exception:
        pass


async def record_debug_log(txt, msg_type=True):
    try:
        await APP["SIGN_DEBUG_LOG"].write(f'''{datetime.datetime.strftime(datetime.datetime.now(), f"[%Y-%m-%d %H:%M:%S] {'DEBUG ' if msg_type else 'WARNING '}")}{txt}\n''')
        await APP["SIGN_DEBUG_LOG"].flush()
    except Exception:
        pass


@retry(wait=wait_fixed(2))
async def get_new_version():
    try:
        resp = await cx_get_request("https://cx-api.waadri.top/get_other_node_version.json")
        if resp["status"] == 1:
            latest_version2 = resp["latest_version"]
            if latest_version2 != str(NODE_VERSION):
                LOGGER.warning(f"节点程序检测到新版本，更新内容如下\n{resp['new_version_log']}")
                LOGGER.warning("正在下载新版本并替换旧版本")
                if in_docker():
                    resp2 = await cx_get_request(resp["docker_download_url"], False)
                else:
                    resp2 = await cx_get_request(resp["py_download_url"], False)
                async with aiofiles.open(__file__, "wb") as f:
                    await f.write(resp2)
                LOGGER.warning("下载完成，正在重启服务……")
                await asyncio.sleep(3)
                for d in list(USER_LIST):
                    await remove_sign_info(d, USER_LIST[d]["name"])
                await APP["SIGN_ERROR_LOG"].close()
                await APP["SIGN_DEBUG_LOG"].close()
                await APP["CX_SESSION"].close()
                async with aiofiles.open(os.path.join(REALPATH, "node_error_log.log"), "w", encoding="utf-8") as log_file:
                    await log_file.close()
                async with aiofiles.open(os.path.join(REALPATH, "node_debug_log.log"), "w", encoding="utf-8") as log_file:
                    await log_file.close()
                os.execl(sys.executable, sys.executable, os.path.abspath(__file__))
        else:
            LOGGER.warning(await json_encode(resp))
    except (aiohttp.client_exceptions.ClientConnectorError, TimeoutError, asyncio.exceptions.TimeoutError, aiohttp.client_exceptions.ServerDisconnectedError, orjson.JSONDecodeError) as e:
        raise e
    except aiohttp.client_exceptions.ClientResponseError as e:
        if e.status == 502 or e.status == 504:
            raise e
        else:
            await record_error_log(traceback.format_exc())
            raise e
    except Exception as e:
        await record_error_log(traceback.format_exc())
        raise e


async def check_new_version_loop():
    while True:
        await asyncio.sleep(60)
        await get_new_version()


async def send_email(uid, name, text, bind_email, email, result, force_send=False):
    try:
        if not force_send:
            if NODE_STRAT_TIME+240 >= time.time():
                await record_debug_log(f"{uid}-{name}:节点刚启动，停止向{email}发送邮件")
                return
            elif NODE_CONFIG["email"]["address"] != "" and bind_email:
                text += "<p style=\"text-indent:2em\">[官方网站] <a href=\"https://cx.waadri.top/login\">https://cx.waadri.top/login</a></p>"
                await record_debug_log(f"{uid}-{name}:开始向{email}发送邮件")
                msg = MIMEText(text, "html", "utf-8")
                msg["From"] = formataddr((NODE_CONFIG["email"]["user"], NODE_CONFIG["email"]["address"]))
                msg["To"] = formataddr(("", email))
                msg["Subject"] = result
                server = aiosmtplib.SMTP(hostname=NODE_CONFIG["email"]["host"], port=NODE_CONFIG["email"]["port"], use_tls=NODE_CONFIG["email"]["use_tls"])
                await server.connect()
                await server.ehlo(hostname="othernode")
                await server.login(NODE_CONFIG["email"]["address"], NODE_CONFIG["email"]["password"])
                await server.sendmail(NODE_CONFIG["email"]["address"], email, msg.as_string())
                try:
                    await server.quit()
                except Exception:
                    pass
                finally:
                    await record_debug_log(f"{uid}-{name}:成功向{email}发送邮件")
        elif NODE_CONFIG["email"]["address"] != "" and bind_email:
            text += "<p style=\"text-indent:2em\">[官方网站] <a href=\"https://cx.waadri.top/login\">https://cx.waadri.top/login</a></p>"
            await record_debug_log(f"{uid}-{name}:开始向{email}发送邮件")
            msg = MIMEText(text, "html", "utf-8")
            msg["From"] = formataddr((NODE_CONFIG["email"]["user"], NODE_CONFIG["email"]["address"]))
            msg["To"] = formataddr(("", email))
            msg["Subject"] = result
            server = aiosmtplib.SMTP(hostname=NODE_CONFIG["email"]["host"], port=NODE_CONFIG["email"]["port"], use_tls=NODE_CONFIG["email"]["use_tls"])
            await server.connect()
            await server.ehlo(hostname="othernode")
            await server.login(NODE_CONFIG["email"]["address"], NODE_CONFIG["email"]["password"])
            await server.sendmail(NODE_CONFIG["email"]["address"], email, msg.as_string())
            try:
                await server.quit()
            except Exception:
                pass
            finally:
                await record_debug_log(f"{uid}-{name}:成功向{email}发送邮件")
    except (aiosmtplib.errors.SMTPServerDisconnected, aiosmtplib.errors.SMTPConnectError, aiosmtplib.errors.SMTPAuthenticationError, ValueError):
        await record_debug_log(f"{uid}-{name}:{NODE_CONFIG['email']['address']}向{email}发送邮件失败，{traceback.format_exc()}", False)
        LOGGER.warning(f"{uid}-{name}:邮件通知发送失败，这可能是由于节点邮件发送配置有误或邮件接收方拉黑了节点配置的发送邮箱")
    except aiosmtplib.errors.SMTPConnectTimeoutError:
        await record_debug_log(f"{uid}-{name}:{NODE_CONFIG['email']['address']}向{email}发送邮件失败，{traceback.format_exc()}", False)
    except Exception:
        await record_debug_log(f"{uid}-{name}:{NODE_CONFIG['email']['address']}向{email}发送邮件失败，{traceback.format_exc()}", False)
        await record_error_log(traceback.format_exc(), False)


async def stop_reason(num, uid, name, bind_email, email):
    try:
        await record_debug_log(f"{uid}-{name}:开始执行签到监控异常停止事件")
        if num == 1:
            reason = "学习通账号登录失败"
        elif num == 2:
            reason = "课程和班级列表获取失败"
        else:
            reason = "未知原因"
        event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
        event_time2 = datetime.datetime.strftime(datetime.datetime.now(), "%Y-%m-%d %H:%M:%S")
        LOGGER.info(f"{uid}-{name}：由于{reason}停止签到监控")
        task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统监控异常停止通知]</p><p style=\"text-indent:2em\">[异常停止时间] {event_time2}</p><p style=\"text-indent:2em\">[异常停止原因] {reason}</p><p style=\"text-indent:2em\">如需重新启动签到监控请重新登录学习通在线自动签到系统并重新启动签到监控。</p>", bind_email, email, "学习通在线自动签到系统监控异常停止通知", True))
        BACKGROUND_TASKS.add(task)
        task.add_done_callback(BACKGROUND_TASKS.discard)
        await send_wechat_message(uid, "other", "学习通在线自动签到系统监控异常停止通知", {"异常停止时间": event_time2, "异常停止原因": reason}, "如需重新启动签到监控请重新登录学习通在线自动签到系统并重新启动签到监控", start_time=event_time2, reason="签到监控异常停止", force_send=True)
        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}签到监控异常停止，停止原因为{reason}"}))
        await send_message(encrypt)
        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "user_logout", "uid": uid, "name": name}))
        await send_message(encrypt)
        await remove_sign_info(uid, name)
        await record_debug_log(f"{uid}-{name}:签到监控异常停止事件执行完成")
    except Exception:
        await record_error_log(traceback.format_exc(), False)


async def interface_two(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid):
    try:
        if 2 in USER_LIST[uid]["port"]:
            res = await get_request(uid, name, USER_LIST[uid]["session"], "https://mobilelearn.chaoxing.com/ppt/activeAPI/taskactivelist", {"courseId": clazzdata["courseid"], "classId": clazzdata["classid"], "uid": uid}, USER_LIST[uid]["header"])
            if res["result"]:
                USER_LIST[uid]["error_num"] = 0
                for data in res["activeList"]:
                    if (data["activeType"] == 2 or data["activeType"] == 74) and data["status"] == 1 and data["startTime"]/1000+86400 > int(time.time()):
                        aid = str(data["id"])
                        if aid not in USER_LIST[uid]["signed_in_list"]:
                            await record_debug_log(f"{uid}-{name}:此活动不在已签到活动列表中，准备签到，活动ID:{aid}")
                            USER_LIST[uid]["signed_in_list"].append(aid)
                            if await check_sign_type(uid, name, aid, sign_type):
                                await record_debug_log(f"{uid}-{name}:此活动符合用户所设置的签到类型，开始签到，活动ID:{aid}")
                                USER_LIST[uid]["sign_task_list"][aid] = asyncio.create_task(signt(uid, name, clazzdata["courseid"], clazzdata["classid"], aid, schoolid, is_numing, sign_num, data["nameOne"], na, 2, tid))
            elif res["errorMsg"] == "请登录后再试":
                await record_debug_log(f"{uid}-{name}:使用接口2获取课程“{na}”的活动列表失败，用户未登录，准备执行签到监控异常停止事件", False)
                task = asyncio.create_task(stop_reason(1, uid, name, USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"]))
                BACKGROUND_TASKS.add(task)
                task.add_done_callback(BACKGROUND_TASKS.discard)
                return 1
            else:
                await record_debug_log(f"{uid}-{name}:使用接口2获取课程“{na}”的活动列表失败，{res['errorMsg']}", False)
                if USER_LIST[uid]["error_num"] < 2:
                    await record_debug_log(f"{uid}-{name}:获取课程“{na}”的活动列表失败次数未超过2次，准备使用接口3进行签到监控", False)
                    if NODE_CONFIG["show_frequently"]:
                        LOGGER.info(f"{uid}-{name}:课程或班级“{na}”的页面提示“{res['errorMsg']}”，将尝试使用接口3（网页端接口）进行签到监控")
                    if 2 in USER_LIST[uid]["port"]:
                        USER_LIST[uid]["port"].remove(2)
                    if 3 not in USER_LIST[uid]["port"]:
                        USER_LIST[uid]["port"].append(3)
                    USER_LIST[uid]["error_num"] += 1
                    return await interface_three(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid)
                else:
                    await record_debug_log(f"{uid}-{name}:获取课程“{na}”的活动列表失败次数超过2次，所有监控接口均被封禁，等待一小时后尝试继续监控", False)
                    event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}在使用接口2（APP端接口）监控课程或班级“{na}”的签到活动时页面提示“{res['errorMsg']}”，所有监控接口均被封禁，等待一小时后尝试继续监控"}))
                    await send_message(encrypt)
                    if NODE_CONFIG["show_frequently"]:
                        LOGGER.info(f"{uid}-{name}:课程或班级“{na}”的页面提示“{res['errorMsg']}”，所有监控接口均被封禁，等待一小时后尝试继续监控")
                    USER_LIST[uid]["error_num"] = 0
                    return 3
        elif 3 in USER_LIST[uid]["port"]:
            await record_debug_log(f"{uid}-{name}:从接口2跳转至接口3来获取课程“{na}”的活动列表")
            return await interface_three(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid)
        elif 4 in USER_LIST[uid]["port"]:
            await record_debug_log(f"{uid}-{name}:从接口2跳转至接口4来获取课程“{na}”的活动列表")
            return await interface_four(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid)
        return None
    except Exception:
        await record_error_log(traceback.format_exc(), False)
        return None


async def interface_three(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid):
    try:
        if 3 in USER_LIST[uid]["port"]:
            if USER_LIST[uid]["schoolid"] == "":
                fid = "0"
            else:
                fid = USER_LIST[uid]["schoolid"]
            res = await get_request(uid, name, USER_LIST[uid]["session"], "https://mobilelearn.chaoxing.com/v2/apis/active/student/activelist", {"fid": fid, "courseId": clazzdata["courseid"], "classId": clazzdata["classid"], "showNotStartedActive": 0, "_": int(time.time()*1000)}, BROWSER_HEADER, ignore_status_code=True)
            if res["result"]:
                USER_LIST[uid]["error_num"] = 0
                for data in res["data"]["activeList"]:
                    if (data["activeType"] == 2 or data["activeType"] == 74) and data["status"] == 1 and data["startTime"]/1000+86400 > int(time.time()):
                        aid = str(data["id"])
                        if aid not in USER_LIST[uid]["signed_in_list"]:
                            await record_debug_log(f"{uid}-{name}:此活动不在已签到活动列表中，准备签到，活动ID:{aid}")
                            USER_LIST[uid]["signed_in_list"].append(aid)
                            if await check_sign_type(uid, name, aid, sign_type):
                                await record_debug_log(f"{uid}-{name}:此活动符合用户所设置的签到类型，开始签到，活动ID:{aid}")
                                USER_LIST[uid]["sign_task_list"][aid] = asyncio.create_task(signt(uid, name, clazzdata["courseid"], clazzdata["classid"], aid, schoolid, is_numing, sign_num, data["nameOne"], na, 3, tid))
            elif res["errorMsg"] == "登录已过期，请重新登录":
                await record_debug_log(f"{uid}-{name}:使用接口3获取课程“{na}”的活动列表失败，用户未登录，准备执行签到监控异常停止事件", False)
                task = asyncio.create_task(stop_reason(1, uid, name, USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"]))
                BACKGROUND_TASKS.add(task)
                task.add_done_callback(BACKGROUND_TASKS.discard)
                return 1
            elif res["errorMsg"] == "非本班学生":
                return 2
            else:
                await record_debug_log(f"{uid}-{name}:使用接口3获取课程“{na}”的活动列表失败，{res['errorMsg']}", False)
                if USER_LIST[uid]["error_num"] < 2:
                    await record_debug_log(f"{uid}-{name}:获取课程“{na}”的活动列表失败次数未超过2次，准备使用接口4进行签到监控", False)
                    if NODE_CONFIG["show_frequently"]:
                        LOGGER.info(f"{uid}-{name}:课程或班级“{na}”的页面提示“{res['errorMsg']}”，将尝试使用接口4（主备用接口）进行签到监控")
                    if 3 in USER_LIST[uid]["port"]:
                        USER_LIST[uid]["port"].remove(3)
                    if 4 not in USER_LIST[uid]["port"]:
                        USER_LIST[uid]["port"].append(4)
                    USER_LIST[uid]["error_num"] += 1
                    return await interface_four(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid)
                else:
                    await record_debug_log(f"{uid}-{name}:获取课程“{na}”的活动列表失败次数超过2次，所有监控接口均被封禁，等待一小时后尝试继续监控", False)
                    event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}在使用接口3（网页端接口）监控课程或班级“{na}”的签到活动时页面提示“{res['errorMsg']}”，所有监控接口均被封禁，等待一小时后尝试继续监控"}))
                    await send_message(encrypt)
                    if NODE_CONFIG["show_frequently"]:
                        LOGGER.info(f"{uid}-{name}:课程或班级“{na}”的页面提示“{res['errorMsg']}”，所有监控接口均被封禁，等待一小时后尝试继续监控")
                    USER_LIST[uid]["error_num"] = 0
                    return 3
        elif 2 in USER_LIST[uid]["port"]:
            await record_debug_log(f"{uid}-{name}:从接口3跳转至接口2来获取课程“{na}”的活动列表")
            return await interface_two(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid)
        elif 4 in USER_LIST[uid]["port"]:
            await record_debug_log(f"{uid}-{name}:从接口3跳转至接口4来获取课程“{na}”的活动列表")
            return await interface_four(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid)
        return None
    except Exception:
        await record_error_log(traceback.format_exc(), False)


async def interface_four(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid):
    try:
        if 4 in USER_LIST[uid]["port"]:
            res = await get_request(uid, name, USER_LIST[uid]["session"], "https://mobilelearn.chaoxing.com/v2/apis/signStat/getUserStat2", {"classId": clazzdata["classid"], "puid": uid, "courseId": clazzdata["courseid"], "duid": uid})
            if res["result"]:
                if res["data"]["allCount"] != clazzdata["sign_number"] or (res["data"]["allCount"] == 0 and res["data"]["earlyCount"] == 0 and res["data"]["absenceCount"] == 0 and res["data"]["attendanceCount"] == 0 and res["data"]["publicCount"] == 0 and res["data"]["personnalCount"] == 0 and res["data"]["lateCount"] == 0 and res["data"]["signPer"] == "0" and res["data"]["sickCount"] == 0 and res["data"]["overdueCount"] == 0):
                    return await interface_four_for_one(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid)
                USER_LIST[uid]["error_num"] = 0
            elif res["errorMsg"] == "请登录后再试":
                await record_debug_log(f"{uid}-{name}:获取课程{na}的签到数量失败，用户未登录，准备执行签到监控异常停止事件", False)
                task = asyncio.create_task(stop_reason(1, uid, name, USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"]))
                BACKGROUND_TASKS.add(task)
                task.add_done_callback(BACKGROUND_TASKS.discard)
                return 1
            elif res["errorMsg"] == "无权限操作":
                return 2
            else:
                await record_error_log(await json_encode(res))
                return await interface_four_for_one(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid)
        elif 2 in USER_LIST[uid]["port"]:
            await record_debug_log(f"{uid}-{name}:从接口4跳转至接口2来获取课程“{na}”的活动列表")
            return await interface_two(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid)
        elif 3 in USER_LIST[uid]["port"]:
            await record_debug_log(f"{uid}-{name}:从接口4跳转至接口3来获取课程“{na}”的活动列表")
            return await interface_three(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid)
        return None
    except Exception:
        await record_error_log(traceback.format_exc())
        return None


async def interface_four_for_one(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid):
    try:
        res = await get_request(uid, name, USER_LIST[uid]["session"], "https://mobilelearn.chaoxing.com/v2/apis/signStat/getActiveList", {"classId": clazzdata["classid"], "courseId": clazzdata["courseid"], "puid": uid, "pageSize": 999999, "duid": uid})
        if res["result"]:
            if res["data"]["total"] != 0:
                clazzdata["sign_number"] = res["data"]["total"]
                USER_LIST[uid]["error_num"] = 0
                for data in res["data"]["list"]:
                    try:
                        starttime = int(parser.parse(data["starttime"]).timestamp())
                    except KeyError:
                        await record_error_log(f"{uid}-{name}:{await json_encode(data)}")
                        continue
                    if (data["activeType"] == 2 or data["activeType"] == 74) and data["status"] == 1 and starttime+86400 >= int(time.time()):
                        aid = str(data["activeid"])
                        if aid not in USER_LIST[uid]["signed_in_list"]:
                            await record_debug_log(f"{uid}-{name}:此活动不在已签到活动列表中，准备签到，活动ID:{aid}")
                            USER_LIST[uid]["signed_in_list"].append(aid)
                            if await check_sign_type(uid, name, aid, sign_type):
                                await record_debug_log(f"{uid}-{name}:此活动发布时间未超过24小时且符合用户所设置的签到类型，开始签到，活动ID:{aid}")
                                USER_LIST[uid]["sign_task_list"][aid] = asyncio.create_task(signt(uid, name, clazzdata["courseid"], clazzdata["classid"], aid, schoolid, is_numing, sign_num, data["name"], na, 4, tid))
            else:
                clazzdata["sign_number"] = 0
                return await interface_four_for_two(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid)
        elif res["errorMsg"] == "请登录后再试":
            await record_debug_log(f"{uid}-{name}:使用接口4的1号接口获取课程“{na}”的活动列表失败，用户未登录，准备执行签到监控异常停止事件", False)
            task = asyncio.create_task(stop_reason(1, uid, name, USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"]))
            BACKGROUND_TASKS.add(task)
            task.add_done_callback(BACKGROUND_TASKS.discard)
            return 1
        elif res["errorMsg"] == "无此用户数据":
            USER_LIST[uid]["error_num"] = 0
            clazzdata["sign_number"] = 0
        elif res["errorMsg"] == "无权限":
            return 2
        else:
            return await interface_four_for_two(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid)
        return None
    except Exception:
        await record_error_log(traceback.format_exc())
        return None


async def interface_four_for_two(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid):
    try:
        res = await get_request(uid, name, USER_LIST[uid]["session"], "https://ketang-zhizhen.chaoxing.com/education/student/activelist", {"DB_STRATEGY": "DEFAULT", "classIds": clazzdata["classid"], "startTimeSet": "", "endTimeSet": "", "statusSet": 1, "keyWord": "", "reload": 0, "devices": 0, "includeWork": 0, "includeExam": 0, "includeRead": 0}, ignore_status_code=True, need_response=True)
        if res["result"]:
            USER_LIST[uid]["error_num"] = 0
            for data in res["data"]["array"]:
                if (data["activeType"] == 2 or data["activeType"] == 74) and data["status"] == 1 and data["startTime"]/1000+86400 > int(time.time()):
                    aid = str(data["id"])
                    if aid not in USER_LIST[uid]["signed_in_list"]:
                        await record_debug_log(f"{uid}-{name}:此活动不在已签到活动列表中，准备签到，活动ID:{aid}")
                        USER_LIST[uid]["signed_in_list"].append(aid)
                        if await check_sign_type(uid, name, aid, sign_type):
                            await record_debug_log(f"{uid}-{name}:此活动符合用户所设置的签到类型，开始签到，活动ID:{aid}")
                            USER_LIST[uid]["sign_task_list"][aid] = asyncio.create_task(signt(uid, name, clazzdata["courseid"], clazzdata["classid"], aid, schoolid, is_numing, sign_num, data["nameOne"], na, 4, tid))
        elif res["errorMsg"] == "error":
            await record_debug_log(f"{uid}-{name}:使用接口4的2号接口获取课程“{na}”的活动列表失败，用户未登录，准备执行签到监控异常停止事件", False)
            task = asyncio.create_task(stop_reason(1, uid, name, USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"]))
            BACKGROUND_TASKS.add(task)
            task.add_done_callback(BACKGROUND_TASKS.discard)
            return 1
        else:
            await record_debug_log(f"{uid}-{name}:使用接口4获取课程“{na}”的活动列表失败，{res['errorMsg']}", False)
            if USER_LIST[uid]["error_num"] < 2:
                await record_debug_log(f"{uid}-{name}:获取课程“{na}”的活动列表失败次数未超过2次，准备使用接口2进行签到监控", False)
                if NODE_CONFIG["show_frequently"]:
                    LOGGER.info(f"{uid}-{name}:课程或班级“{na}”的页面提示“{res['errorMsg']}”，将尝试使用接口2（APP端接口）进行签到监控")
                if 4 in USER_LIST[uid]["port"]:
                    USER_LIST[uid]["port"].remove(4)
                if 2 not in USER_LIST[uid]["port"]:
                    USER_LIST[uid]["port"].append(2)
                USER_LIST[uid]["error_num"] += 1
                return await interface_two(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid)
            else:
                await record_debug_log(f"{uid}-{name}:获取课程“{na}”的活动列表失败次数超过2次，所有监控接口均被封禁，等待一小时后尝试继续监控", False)
                event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}在使用接口4（主备用接口）监控课程或班级“{na}”的签到活动时页面提示“{res['errorMsg']}”，所有监控接口均被封禁，等待一小时后尝试继续监控"}))
                await send_message(encrypt)
                if NODE_CONFIG["show_frequently"]:
                    LOGGER.info(f"{uid}-{name}:课程或班级“{na}”的页面提示“{res['errorMsg']}”，所有监控接口均被封禁，等待一小时后尝试继续监控")
                USER_LIST[uid]["error_num"] = 0
                return 3
        return None
    except Exception:
        await record_error_log(traceback.format_exc())
        return None


async def get_timelong(timelong):
    total_seconds = timelong // 1000
    days = total_seconds // 86400
    total_seconds %= 86400
    hours = total_seconds // 3600
    total_seconds %= 3600
    minutes = total_seconds // 60
    return f"{days}天{hours}小时{minutes}分钟"


async def signt(uid, name, course_id, class_id, aid, schoolid, is_numing, sign_num, name_one, na, now_port, tid):
    try:
        if now_port != 1:
            event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}课程或班级“{na}”监测到签到活动，签到活动名称为“{name_one}”"}))
            await send_message(encrypt)
            LOGGER.info(f"{uid}-{name}:课程或班级“{na}”监测到签到活动，签到活动名称为“{name_one}”")
        res = await getpptactiveinfo(uid, name, aid)
        if res is False:
            return
        ifNeedVCode = res["data"]["ifNeedVCode"]
        aid_list = []
        if res["data"].get("multiClassesActives"):
            await record_debug_log(f"{uid}-{name}:该签到设置了多班发放")
            for m in res["data"]["multiClassesActives"]:
                aid_list.append(str(m["aid"]))
        else:
            await record_debug_log(f"{uid}-{name}:该签到未设置多班发放")
            aid_list.append(aid)
        start_time = res["data"]["starttimeStr"]
        start_timestamp = int(res["data"]["starttime"]/1000)
        if not res["data"]["manual"]:
            await record_debug_log(f"{uid}-{name}:该签到未设置手动结束")
            end_time = wechat_end_time = res["data"]["endtimeStr"]
            timelong = f"{res['data']['day']}天{res['data']['hour']}小时{res['data']['minute']}分钟"
        else:
            await record_debug_log(f"{uid}-{name}:该签到为手动结束")
            end_time = "无"
            wechat_end_time = datetime.datetime.strftime(datetime.datetime.fromtimestamp(start_timestamp+86400), "%Y-%m-%d %H:%M:%S")
            timelong = "教师手动结束签到"
        if res["data"].get("timer"):
            check_aid = str(res["data"]["timer"]["timerSignId"])
        else:
            check_aid = aid
        signout_email_append_text = ""
        signout_wechat_append_text = {}
        if res["data"]["activeType"] == 2:
            if res["data"].get("openSignOutFlag"):
                await record_debug_log(f"{uid}-{name}:该签到设置了下课签退")
                signout_start_time = datetime.datetime.strftime(datetime.datetime.fromtimestamp(res["data"]["signOutPublishTimeStamp"]/1000-5), "%Y-%m-%d %H:%M:%S")
                signout_timelong = await get_timelong(res["data"]["signOutDuration"])
                activetype_append_text = "，且教师设置了下课签退"
                signout_email_append_text = f"<p style=\"text-indent:2em\">[签退大致开始时间] {signout_start_time}</p><p style=\"text-indent:2em\">[签退持续时间] {signout_timelong}</p>"
                signout_wechat_append_text = {"签退大致开始时间": signout_start_time, "签退持续时间": signout_timelong}
            else:
                await record_debug_log(f"{uid}-{name}:该签到未设置下课签退")
                activetype_append_text = "，且教师未设置下课签退"
        else:
            await record_debug_log(f"{uid}-{name}:该签到为下课签退")
            activetype_append_text = "，且该签到为下课签退"
        event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
        event_time2 = datetime.datetime.strftime(datetime.datetime.now(), "%Y-%m-%d %H:%M:%S")
        set_address = ""
        set_longitude = -1
        set_latitude = -1
        if res["data"]["otherId"] == 2:
            await record_debug_log(f"{uid}-{name}:该签到为二维码签到")
            if res["data"]["ifrefreshewm"] == 1 and res["data"]["ifopenAddress"] == 1:
                await record_debug_log(f"{uid}-{name}:该签到二维码会刷新且指定了签到位置，开始获取教师指定位置信息")
                sign_location_info = await get_sign_location_info(uid, name, check_aid)
                address = sign_location_info["address"]
                if address is None:
                    await record_debug_log(f"{uid}-{name}:未能成功获取签到指定位置信息，原因为“{sign_location_info['msg']}”", False)
                    send_text1 = f"指定位置信息解析失败，失败原因为“{sign_location_info['msg']}”，等待同班同学使用微信小程序“WAADRI的工具箱”指定签到位置并扫描学习通签到二维码"
                    send_text2 = f"，但指定位置信息解析失败，失败原因为“{sign_location_info['msg']}”，请让同班同学使用微信小程序“WAADRI的工具箱”指定签到位置并扫描学习通签到二维码来完成自动签到"
                else:
                    await record_debug_log(f"{uid}-{name}:成功获取签到指定位置信息")
                    set_address = address
                    set_longitude = sign_location_info["longitude"]
                    set_latitude = sign_location_info["latitude"]
                    send_text1 = "等待同班同学使用微信小程序“WAADRI的工具箱”扫描学习通签到二维码"
                    send_text2 = "，请让同班同学使用微信小程序“WAADRI的工具箱”扫描学习通签到二维码来完成自动签到"
                sign_type = f"{res['data']['ewmRefreshTime']}秒自动更新且指定了签到地点的二维码签到"
                task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统二维码签到等待扫码通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[对应课程或班级] {na}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] {res['data']['ewmRefreshTime']}秒自动更新且指定了签到地点的二维码签到{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {start_time}</p><p style=\"text-indent:2em\">[签到结束时间] {end_time}</p><p style=\"text-indent:2em\">[签到持续时间] {timelong}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[扫码小程序使用教程] <a href=\"https://doc.waadri.top/guide/%E4%BA%8C%E7%BB%B4%E7%A0%81%E7%AD%BE%E5%88%B0.html\">小程序使用教程点这里</a></p><p style=\"text-indent:2em\">[签到状态] {send_text1}来完成自动签到</p><p style=\"text-indent:2em\">微信小程序二维码：</p><img src=\"https://cx-static.waadri.top/image/gh_3c371f2be720_1280.jpg\" style=\"width:100%;height:auto;max-width:200px;max-height:auto\">", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通二维码签到等待扫码通知"))
                BACKGROUND_TASKS.add(task)
                task.add_done_callback(BACKGROUND_TASKS.discard)
                await send_wechat_message(uid, "sign", "发现签到，等待扫码", f"{send_text1}来完成自动签到", icon="time", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"{res['data']['ewmRefreshTime']}秒自动更新且指定了签到地点的二维码签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text, is_qrcode_sign=True)
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到为{res['data']['ewmRefreshTime']}秒自动更新且指定了签到地点的二维码签到{activetype_append_text}{send_text2}，小程序使用教程见https://doc.waadri.top/guide/%E4%BA%8C%E7%BB%B4%E7%A0%81%E7%AD%BE%E5%88%B0.html"}))
                await send_message(encrypt)
                LOGGER.info(f"{uid}-{name}:监测到{res['data']['ewmRefreshTime']}秒自动更新且指定了签到地点的二维码签到{activetype_append_text}")
            elif res["data"]["ifrefreshewm"] == 1:
                await record_debug_log(f"{uid}-{name}:该签到二维码会刷新且没有指定签到位置")
                sign_type = f"{res['data']['ewmRefreshTime']}秒自动更新且未指定签到地点的二维码签到"
                task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统二维码签到等待扫码通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[对应课程或班级] {na}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] {res['data']['ewmRefreshTime']}秒自动更新且未指定签到地点的二维码签到{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {start_time}</p><p style=\"text-indent:2em\">[签到结束时间] {end_time}</p><p style=\"text-indent:2em\">[签到持续时间] {timelong}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[扫码小程序使用教程] <a href=\"https://doc.waadri.top/guide/%E4%BA%8C%E7%BB%B4%E7%A0%81%E7%AD%BE%E5%88%B0.html\">小程序使用教程点这里</a></p><p style=\"text-indent:2em\">[签到状态] 等待同班同学使用微信小程序“WAADRI的工具箱”扫描学习通签到二维码来完成自动签到</p><p style=\"text-indent:2em\">微信小程序二维码：</p><img src=\"https://cx-static.waadri.top/image/gh_3c371f2be720_1280.jpg\" style=\"width:100%;height:auto;max-width:200px;max-height:auto\">", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通二维码签到等待扫码通知"))
                BACKGROUND_TASKS.add(task)
                task.add_done_callback(BACKGROUND_TASKS.discard)
                await send_wechat_message(uid, "sign", "发现签到，等待扫码", "等待同班同学使用微信小程序“WAADRI的工具箱”扫描学习通签到二维码来完成自动签到", icon="time", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"{res['data']['ewmRefreshTime']}秒自动更新且未指定签到地点的二维码签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text, is_qrcode_sign=True)
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到为{res['data']['ewmRefreshTime']}秒自动更新且未指定签到地点的二维码签到{activetype_append_text}，请让同班同学使用微信小程序“WAADRI的工具箱”扫描学习通签到二维码来完成自动签到，小程序使用教程见https://doc.waadri.top/guide/%E4%BA%8C%E7%BB%B4%E7%A0%81%E7%AD%BE%E5%88%B0.html"}))
                await send_message(encrypt)
                LOGGER.info(f"{uid}-{name}:监测到{res['data']['ewmRefreshTime']}秒自动更新且未指定签到地点的二维码签到{activetype_append_text}")
            elif res["data"]["ifopenAddress"] == 1:
                await record_debug_log(f"{uid}-{name}:该签到二维码不会刷新且指定了签到位置，开始获取教师指定位置信息")
                sign_location_info = await get_sign_location_info(uid, name, check_aid)
                address = sign_location_info["address"]
                if address is None:
                    await record_debug_log(f"{uid}-{name}:未能成功获取签到指定位置信息，原因为“{sign_location_info['msg']}”", False)
                    send_text1 = f"指定位置信息解析失败，失败原因为“{sign_location_info['msg']}”，等待同班同学使用微信小程序“WAADRI的工具箱”指定签到位置并扫描学习通签到二维码"
                    send_text2 = f"，但指定位置信息解析失败，失败原因为“{sign_location_info['msg']}”，请让同班同学使用微信小程序“WAADRI的工具箱”指定签到位置并扫描学习通签到二维码来完成自动签到"
                else:
                    await record_debug_log(f"{uid}-{name}:成功获取签到指定位置信息")
                    set_address = address
                    set_longitude = sign_location_info["longitude"]
                    set_latitude = sign_location_info["latitude"]
                    send_text1 = "等待同班同学使用微信小程序“WAADRI的工具箱”扫描学习通签到二维码"
                    send_text2 = "，请让同班同学使用微信小程序“WAADRI的工具箱”扫描学习通签到二维码来完成自动签到"
                sign_type = "无自动更新且指定了签到地点的二维码签到"
                task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统二维码签到等待扫码通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[对应课程或班级] {na}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] 无自动更新且指定了签到地点的二维码签到{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {start_time}</p><p style=\"text-indent:2em\">[签到结束时间] {end_time}</p><p style=\"text-indent:2em\">[签到持续时间] {timelong}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[扫码小程序使用教程] <a href=\"https://doc.waadri.top/guide/%E4%BA%8C%E7%BB%B4%E7%A0%81%E7%AD%BE%E5%88%B0.html\">小程序使用教程点这里</a></p><p style=\"text-indent:2em\">[签到状态] {send_text1}来完成自动签到</p><p style=\"text-indent:2em\">微信小程序二维码：</p><img src=\"https://cx-static.waadri.top/image/gh_3c371f2be720_1280.jpg\" style=\"width:100%;height:auto;max-width:200px;max-height:auto\">", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通二维码签到等待扫码通知"))
                BACKGROUND_TASKS.add(task)
                task.add_done_callback(BACKGROUND_TASKS.discard)
                await send_wechat_message(uid, "sign", "发现签到，等待扫码", f"{send_text1}来完成自动签到", icon="time", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"无自动更新且指定了签到地点的二维码签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text, is_qrcode_sign=True)
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到为无自动更新且指定了签到地点的二维码签到{activetype_append_text}{send_text2}，小程序使用教程见https://doc.waadri.top/guide/%E4%BA%8C%E7%BB%B4%E7%A0%81%E7%AD%BE%E5%88%B0.html"}))
                await send_message(encrypt)
                LOGGER.info(f"{uid}-{name}:监测到无自动更新且指定了签到地点的二维码签到{activetype_append_text}")
            else:
                await record_debug_log(f"{uid}-{name}:该签到二维码不会刷新且没有指定签到位置")
                sign_type = "无自动更新且未指定签到地点的二维码签到"
                task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统二维码签到等待扫码通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[对应课程或班级] {na}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] 无自动更新且未指定签到地点的二维码签到{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {start_time}</p><p style=\"text-indent:2em\">[签到结束时间] {end_time}</p><p style=\"text-indent:2em\">[签到持续时间] {timelong}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[扫码小程序使用教程] <a href=\"https://doc.waadri.top/guide/%E4%BA%8C%E7%BB%B4%E7%A0%81%E7%AD%BE%E5%88%B0.html\">小程序使用教程点这里</a></p><p style=\"text-indent:2em\">[签到状态] 等待同班同学使用微信小程序“WAADRI的工具箱”扫描学习通签到二维码来完成自动签到</p><p style=\"text-indent:2em\">微信小程序二维码：</p><img src=\"https://cx-static.waadri.top/image/gh_3c371f2be720_1280.jpg\" style=\"width:100%;height:auto;max-width:200px;max-height:auto\">", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通二维码签到等待扫码通知"))
                BACKGROUND_TASKS.add(task)
                task.add_done_callback(BACKGROUND_TASKS.discard)
                await send_wechat_message(uid, "sign", "发现签到，等待扫码", "等待同班同学使用微信小程序“WAADRI的工具箱”扫描学习通签到二维码来完成自动签到", icon="time", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"无自动更新且未指定签到地点的二维码签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text, is_qrcode_sign=True)
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到为无自动更新且未指定签到地点的二维码签到{activetype_append_text}，请让同班同学使用微信小程序“WAADRI的工具箱”扫描学习通签到二维码来完成自动签到，小程序使用教程见https://doc.waadri.top/guide/%E4%BA%8C%E7%BB%B4%E7%A0%81%E7%AD%BE%E5%88%B0.html"}))
                await send_message(encrypt)
                LOGGER.info(f"{uid}-{name}:监测到无自动更新且未指定签到地点的二维码签到{activetype_append_text}")
            temp_data = {"name": name, "courseid": course_id, "classid": class_id, "aid": aid, "aid_list": aid_list, "uid": uid, "lesson_name": na, "address": set_address, "longitude": set_longitude, "latitude": set_latitude, "event_time2": event_time2, "name_one": name_one, "sign_type": sign_type, "start_time": start_time, "end_time": end_time, "wechat_end_time": wechat_end_time, "timelong": timelong, "sign_status": False, "activetype_append_text": activetype_append_text, "signout_email_append_text": signout_email_append_text, "signout_wechat_append_text": signout_wechat_append_text, "start_timestamp": start_timestamp}
            QRCODE_SIGN_DICT[f"{uid}{aid}"] = temp_data
            await record_debug_log(f"{uid}-{name}:签到相关信息写入二维码签到字典队列中")
            data = {"type": "get_qrcode", "qrcode_sign_list": aid_list}
            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode(data))
            await send_message(encrypt)
            USER_LIST[uid]["sign_task_list"].pop(aid, None)
            await record_debug_log(f"{uid}-{name}:从签到任务列表中移除当前任务，aid:{aid}")
        else:
            if schoolid == "":
                fid = "0"
            else:
                fid = schoolid
            sign_data = {
                "activeId": aid,
                "uid": uid,
                "clientip": "",
                "latitude": "-1",
                "longitude": "-1",
                "appType": "15",
                "fid": fid,
                "name": name
            }
            other_append_text = ""
            sign_type = ""
            if res["data"]["otherId"] == 0:
                if res["data"]["ifphoto"] == 1:
                    await record_debug_log(f"{uid}-{name}:该签到为拍照签到")
                    await send_wechat_message(uid, "sign", "发现签到", "监控到签到活动，准备签到", icon="time", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"拍照签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                    if USER_LIST[uid]["set_objectId"]:
                        await record_debug_log(f"{uid}-{name}:已设置默认拍照图片，直接签到")
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到为拍照签到{activetype_append_text}"}))
                        await send_message(encrypt)
                        LOGGER.info(f"{uid}-{name}:该签到为拍照签到{activetype_append_text}")
                    else:
                        await record_debug_log(f"{uid}-{name}:未设置默认拍照图片，直接签到")
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到为拍照签到{activetype_append_text}，但您未设置默认拍照图片，将不提交拍照图片进行自动签到"}))
                        await send_message(encrypt)
                        LOGGER.info(f"{uid}-{name}:该签到为拍照签到{activetype_append_text}，但用户未设置默认拍照图片，将不提交拍照图片进行自动签到")
                        other_append_text = "未设置默认拍照图片，不提交拍照图片"
                    sign_type = "拍照签到"
                    sign_data["useragent"] = ""
                    sign_data["objectId"] = USER_LIST[uid]["objectId"]
                    sign_data["validate"] = ""
                else:
                    await record_debug_log(f"{uid}-{name}:该签到为普通签到")
                    await send_wechat_message(uid, "sign", "发现签到", "监控到签到活动，准备签到", icon="time", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"普通签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                    await record_debug_log(f"{uid}-{name}:直接签到")
                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到为普通签到{activetype_append_text}"}))
                    await send_message(encrypt)
                    LOGGER.info(f"{uid}-{name}:该签到为普通签到{activetype_append_text}")
                    sign_type = "普通签到"
                    sign_data["useragent"] = ""
            elif res["data"]["otherId"] == 3:
                await record_debug_log(f"{uid}-{name}:该签到为手势签到，开始获取签到手势")
                await send_wechat_message(uid, "sign", "发现签到，开始爆破签到信息", "监控到签到活动，开始爆破签到手势码", icon="time", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"手势签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                LOGGER.info(f"{uid}-{name}:该签到为手势签到{activetype_append_text}，开始请求爆破服务器对签到手势码进行爆破")
                sign_type = "手势签到"
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到为手势签到{activetype_append_text}，开始请求爆破服务器对签到手势码进行爆破，爆破时间可能较长，请耐心等待，每日凌晨0点至6点爆破服务器不工作，爆破失败为正常现象"}))
                await send_message(encrypt)
                sign_code_info = await get_sign_code_info(uid, name, check_aid)
                signCode = sign_code_info["code"]
                attack_time = sign_code_info["attack_time"]
                event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                if signCode is not None:
                    await send_wechat_message(uid, "sign", "签到信息爆破成功，准备签到", f"签到手势码爆破成功，用时{attack_time}秒，准备签到", icon="time", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"手势签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}签到手势码爆破成功，用时{attack_time}秒"}))
                    await send_message(encrypt)
                    await record_debug_log(f"{uid}-{name}:成功获取签到手势，开始签到")
                    LOGGER.info(f"{uid}-{name}:签到手势码爆破成功，用时{attack_time}秒")
                    sign_data["signCode"] = signCode
                else:
                    await record_debug_log(f"{uid}-{name}:未能成功获取签到手势，原因为“{sign_code_info['msg']}”，取消签到", False)
                    task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统签到失败通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[对应课程或班级] {na}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] 手势签到{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {start_time}</p><p style=\"text-indent:2em\">[签到结束时间] {end_time}</p><p style=\"text-indent:2em\">[签到持续时间] {timelong}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[签到状态] 签到失败，未能爆破出签到手势码，原因为“{sign_code_info['msg']}”</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通手势签到结果：签到失败"))
                    BACKGROUND_TASKS.add(task)
                    task.add_done_callback(BACKGROUND_TASKS.discard)
                    await send_wechat_message(uid, "sign", "签到失败", f"签到失败，未能爆破出签到手势码，原因为“{sign_code_info['msg']}”", icon="close-octagon", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"手势签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}签到手势码爆破失败，失败原因为“{sign_code_info['msg']}”，取消签到"}))
                    await send_message(encrypt)
                    LOGGER.info(f"{uid}-{name}:签到手势码爆破失败，失败原因为“{sign_code_info['msg']}”，取消签到")
                    USER_LIST[uid]["sign_task_list"].pop(aid, None)
                    await record_debug_log(f"{uid}-{name}:从签到任务列表中移除当前任务，aid:{aid}")
                    return
            elif res["data"]["otherId"] == 4:
                if res["data"]["ifopenAddress"] == 1:
                    await record_debug_log(f"{uid}-{name}:该签到为指定位置签到，开始获取签到指定位置信息")
                    await send_wechat_message(uid, "sign", "发现签到，开始解析签到信息", "监控到签到活动，开始解析指定位置信息", icon="time", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"指定位置签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                    sign_type = "指定位置签到"
                    sign_location_info = await get_sign_location_info(uid, name, check_aid)
                    address = sign_location_info["address"]
                    if address is not None:
                        await record_debug_log(f"{uid}-{name}:成功获取签到指定位置信息，开始签到")
                        await send_wechat_message(uid, "sign", "签到信息解析成功", "指定位置信息解析成功，准备签到", icon="time", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"指定位置签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到为指定位置签到{activetype_append_text}"}))
                        await send_message(encrypt)
                        sign_data["latitude"] = sign_location_info["latitude"]
                        sign_data["longitude"] = sign_location_info["longitude"]
                        sign_data["address"] = address
                        LOGGER.info(f"{uid}-{name}:该签到为指定位置签到{activetype_append_text}")
                    else:
                        await record_debug_log(f"{uid}-{name}:未能成功获取签到指定位置信息，原因为“{sign_location_info['msg']}”，取消签到", False)
                        LOGGER.info(f"{uid}-{name}:该签到为指定位置签到{activetype_append_text}，但指定位置信息解析失败，失败原因为“{sign_location_info['msg']}”")
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到为指定位置签到{activetype_append_text}，但指定位置信息解析失败，失败原因为“{sign_location_info['msg']}”"}))
                        await send_message(encrypt)
                        task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统签到失败通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[对应课程或班级] {na}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] 指定位置签到{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {start_time}</p><p style=\"text-indent:2em\">[签到结束时间] {end_time}</p><p style=\"text-indent:2em\">[签到持续时间] {timelong}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[签到状态] 签到失败，指定位置信息解析失败，失败原因为“{sign_location_info['msg']}”</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通指定位置签到结果：签到失败"))
                        BACKGROUND_TASKS.add(task)
                        task.add_done_callback(BACKGROUND_TASKS.discard)
                        await send_wechat_message(uid, "sign", "签到失败", f"签到失败，指定位置信息解析失败，失败原因为“{sign_location_info['msg']}”", icon="close-octagon", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"指定位置签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}自动签到失败，失败原因为“指定位置信息解析失败”"}))
                        await send_message(encrypt)
                        LOGGER.info(f"{uid}-{name}:自动签到失败，失败原因为“指定位置信息解析失败”")
                        USER_LIST[uid]["sign_task_list"].pop(aid, None)
                        await record_debug_log(f"{uid}-{name}:从签到任务列表中移除当前任务，aid:{aid}")
                        return
                    sign_data["ifTiJiao"] = "1"
                    sign_data["validate"] = ""
                    sign_data["vpProbability"] = 0
                    sign_data["vpStrategy"] = ""
                else:
                    await record_debug_log(f"{uid}-{name}:该签到为普通位置签到")
                    await send_wechat_message(uid, "sign", "发现签到", "监控到签到活动，准备签到", icon="time", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"普通位置签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                    if USER_LIST[uid]["set_address"]:
                        await record_debug_log(f"{uid}-{name}:已设置默认位置信息，直接签到")
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到为普通位置签到{activetype_append_text}"}))
                        await send_message(encrypt)
                        LOGGER.info(f"{uid}-{name}:该签到为普通位置签到{activetype_append_text}")
                    else:
                        await record_debug_log(f"{uid}-{name}:未设置默认位置信息，直接签到")
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到为普通位置签到{activetype_append_text}，但您未设置默认位置信息，将不提交位置信息进行自动签到"}))
                        await send_message(encrypt)
                        LOGGER.info(f"{uid}-{name}:该签到为普通位置签到{activetype_append_text}，但用户未设置默认位置信息，将不提交位置信息进行自动签到")
                        other_append_text = "未设置默认位置信息，不提交位置信息"
                    sign_type = "普通位置签到"
                    sign_data["latitude"] = USER_LIST[uid]["latitude"]
                    sign_data["longitude"] = USER_LIST[uid]["longitude"]
                    sign_data["address"] = USER_LIST[uid]["address"]
                    sign_data["ifTiJiao"] = "1"
                    sign_data["validate"] = ""
                    sign_data["vpProbability"] = 0
                    sign_data["vpStrategy"] = ""
            elif res["data"]["otherId"] == 5:
                await record_debug_log(f"{uid}-{name}:该签到为签到码签到，开始获取签到码")
                await send_wechat_message(uid, "sign", "发现签到，开始爆破签到信息", "监控到签到活动，开始爆破签到码", icon="time", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"签到码签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                LOGGER.info(f"{uid}-{name}:该签到为签到码签到{activetype_append_text}，开始请求爆破服务器对签到码进行爆破")
                sign_type = "签到码签到"
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到为签到码签到{activetype_append_text}，开始请求爆破服务器对签到码进行爆破，爆破时间可能较长，请耐心等待，每日凌晨0点至6点爆破服务器不工作，爆破失败为正常现象"}))
                await send_message(encrypt)
                sign_code_info = await get_sign_code_info(uid, name, check_aid)
                signCode = sign_code_info["code"]
                attack_time = sign_code_info["attack_time"]
                event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                if signCode is not None:
                    await send_wechat_message(uid, "sign", "签到信息爆破成功，准备签到", f"签到码爆破成功，用时{attack_time}秒，准备签到", icon="time", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"签到码签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}签到码爆破成功，用时{attack_time}秒"}))
                    await send_message(encrypt)
                    await record_debug_log(f"{uid}-{name}:成功获取签到码，开始签到")
                    LOGGER.info(f"{uid}-{name}:签到码爆破成功，用时{attack_time}秒")
                    sign_data["signCode"] = signCode
                else:
                    await record_debug_log(f"{uid}-{name}:未能成功获取签到码，原因为“{sign_code_info['msg']}”，取消签到", False)
                    task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统签到失败通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[对应课程或班级] {na}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] 签到码签到{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {start_time}</p><p style=\"text-indent:2em\">[签到结束时间] {end_time}</p><p style=\"text-indent:2em\">[签到持续时间] {timelong}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[签到状态] 签到失败，未能爆破出签到码，原因为“{sign_code_info['msg']}”</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通签到码签到结果：签到失败"))
                    BACKGROUND_TASKS.add(task)
                    task.add_done_callback(BACKGROUND_TASKS.discard)
                    await send_wechat_message(uid, "sign", "签到失败", f"签到失败，未能爆破出签到码，原因为“{sign_code_info['msg']}”", icon="close-octagon", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"签到码签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}签到码爆破失败，失败原因为“{sign_code_info['msg']}”，取消签到"}))
                    await send_message(encrypt)
                    LOGGER.info(f"{uid}-{name}:签到码爆破失败，失败原因为“{sign_code_info['msg']}”，取消签到")
                    USER_LIST[uid]["sign_task_list"].pop(aid, None)
                    await record_debug_log(f"{uid}-{name}:从签到任务列表中移除当前任务，aid:{aid}")
                    return
            if now_port == 1 and sign_type != "手势签到" and sign_type != "签到码签到":
                event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}等待9秒后开始检测是否需要进行安全验证"}))
                await send_message(encrypt)
                LOGGER.info(f"{uid}-{name}:等待9秒后开始检测是否需要进行安全验证")
                await asyncio.sleep(9)
            while True:
                try:
                    await record_debug_log(f"{uid}-{name}:开始预签到")
                    await get_request(uid, name, USER_LIST[uid]["session"], "https://mobilelearn.chaoxing.com/newsign/preSign", {"courseId": course_id, "classId": class_id, "activePrimaryId": aid, "general": 1, "sys": 1, "ls": 1, "appType": 15, "uid": uid, "tid": tid, "ut": "s"}, USER_LIST[uid]["header"], json_type=False)
                    await record_debug_log(f"{uid}-{name}:预签到完成，开始检查是否需要进行安全验证")
                    if ifNeedVCode:
                        await record_debug_log(f"{uid}-{name}:签到需要进行安全验证，aid:{aid}")
                        event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到需要进行安全验证，尝试通过验证"}))
                        await send_message(encrypt)
                        LOGGER.info(f"{uid}-{name}:该签到需要进行安全验证，尝试通过验证")
                        sign_validate_info = await get_sign_validate_info(uid, name, aid)
                        validate = sign_validate_info["validate"]
                        if validate is not None:
                            sign_data["validate"] = validate
                            event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}安全验证已通过，开始进行预签到"}))
                            await send_message(encrypt)
                            LOGGER.info(f"{uid}-{name}:安全验证已通过，开始进行预签到")
                        else:
                            await record_debug_log(f"{uid}-{name}:签到无法通过安全验证，取消签到，aid:{aid}", False)
                            task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统签到失败通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[对应课程或班级] {na}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] {sign_type}{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {start_time}</p><p style=\"text-indent:2em\">[签到结束时间] {end_time}</p><p style=\"text-indent:2em\">[签到持续时间] {timelong}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[签到状态] 由于签到需要进行安全验证且无法通过验证导致签到失败，请使用官方节点进行签到或自行登录学习通APP进行签到</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], f"学习通{sign_type}结果：签到失败"))
                            BACKGROUND_TASKS.add(task)
                            task.add_done_callback(BACKGROUND_TASKS.discard)
                            await send_wechat_message(uid, "sign", "签到失败", "由于签到需要进行安全验证且无法通过验证导致签到失败，请使用官方节点进行签到或自行登录学习通APP进行签到", icon="close-octagon", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"{sign_type}{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                            event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}由于签到需要进行安全验证且无法通过验证导致签到失败，请使用官方节点进行签到或自行登录学习通APP进行签到"}))
                            await send_message(encrypt)
                            LOGGER.info(f"{uid}-{name}:由于签到需要进行安全验证且无法通过验证导致签到失败，因此取消签到")
                            USER_LIST[uid]["sign_task_list"].pop(aid, None)
                            await record_debug_log(f"{uid}-{name}:从签到任务列表中移除当前任务，aid:{aid}")
                            return
                    else:
                        await record_debug_log(f"{uid}-{name}:签到无需进行安全验证，aid:{aid}")
                        event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到无需进行安全验证，将直接进行签到"}))
                        await send_message(encrypt)
                        LOGGER.info(f"{uid}-{name}:该签到无需进行安全验证，将直接进行签到")
                    analysis_res = await get_request(uid, name, USER_LIST[uid]["session"], "https://mobilelearn.chaoxing.com/pptSign/analysis", {"vs": 1, "DB_STRATEGY": "RANDOM", "aid": aid}, USER_LIST[uid]["header"], json_type=False)
                    md5_pattern = re.compile(r"[a-f0-9]{32}")
                    md5_hash = md5_pattern.search(analysis_res)
                    if md5_hash:
                        md5_hash = md5_hash.group()
                        await get_request(uid, name, USER_LIST[uid]["session"], "https://mobilelearn.chaoxing.com/pptSign/analysis2", {"DB_STRATEGY": "RANDOM", "code": md5_hash}, USER_LIST[uid]["header"], json_type=False)
                    event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}预签到请求成功，等待1秒后开始签到"}))
                    await send_message(encrypt)
                    LOGGER.info(f"{uid}-{name}:预签到请求成功，等待1秒后开始签到")
                    await asyncio.sleep(1)
                    sign_data["deviceCode"] = USER_LIST[uid]["deviceCode"]
                    text = await get_request(uid, name, USER_LIST[uid]["session"], "https://mobilelearn.chaoxing.com/pptSign/stuSignajax", sign_data, USER_LIST[uid]["header"], json_type=False)
                    if text == "validate" and not ifNeedVCode:
                        await record_debug_log(f"{uid}-{name}:出现validate提示，尝试强制执行安全验证，aid:{aid}", False)
                        ifNeedVCode = 1
                        continue
                    break
                except Exception:
                    await record_error_log(traceback.format_exc())
            if text == "请先登录再进行签到":
                await record_debug_log(f"{uid}-{name}:出现提示请先登录再进行签到，准备执行签到监控异常停止事件", False)
                task = asyncio.create_task(stop_reason(1, uid, name, USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"]))
                BACKGROUND_TASKS.add(task)
                task.add_done_callback(BACKGROUND_TASKS.discard)
                return
            if text == "success":
                USER_LIST[uid]["success_sign_num"] += 1
                await send_email(uid, name, f"<p>[学习通在线自动签到系统签到成功通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[对应课程或班级] {na}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] {sign_type}{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {start_time}</p><p style=\"text-indent:2em\">[签到结束时间] {end_time}</p><p style=\"text-indent:2em\">[签到持续时间] {timelong}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[签到状态] {other_append_text}签到成功</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], f"学习通{sign_type}结果：签到成功")
                await send_wechat_message(uid, "sign", "签到成功", f"{other_append_text}签到成功", icon="check-circle", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"{sign_type}{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}自动签到成功"}))
                await send_message(encrypt)
                LOGGER.info(f"{uid}-{name}:自动签到成功")
                if is_numing and USER_LIST[uid]["success_sign_num"] >= sign_num:
                    event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                    event_time2 = datetime.datetime.strftime(datetime.datetime.now(), "%Y-%m-%d %H:%M:%S")
                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}定次签到模式已完成指定成功签到次数"}))
                    await send_message(encrypt)
                    await send_email(uid, name, f"<p>[学习通在线自动签到系统停止监控通知]</p><p style=\"text-indent:2em\">[监控停止时间] {event_time2}</p><p style=\"text-indent:2em\">[监控停止原因] 定次签到模式完成指定成功签到次数</p><p style=\"text-indent:2em\">如需重新启动签到监控请登录学习通在线自动签到系统并重新启动签到监控。</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通在线自动签到系统停止监控通知")
                    await send_wechat_message(uid, "other", "学习通在线自动签到系统停止监控通知", {"监控停止时间": event_time2, "监控停止原因": "定次签到模式完成指定成功签到次数"}, "如需重新启动签到监控请登录学习通在线自动签到系统并重新启动签到监控", start_time=event_time2, reason="签到监控正常停止")
                    LOGGER.info(f"{uid}-{name}:定次签到模式已完成指定成功签到次数")
                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "need_stop_sign", "uid": uid, "name": name}))
                    await send_message(encrypt)
            elif text == "success2":
                task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统签到失败通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[对应课程或班级] {na}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] {sign_type}{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {start_time}</p><p style=\"text-indent:2em\">[签到结束时间] {end_time}</p><p style=\"text-indent:2em\">[签到持续时间] {timelong}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[签到状态] {other_append_text}签到失败，签到已结束</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], f"学习通{sign_type}结果：签到失败"))
                BACKGROUND_TASKS.add(task)
                task.add_done_callback(BACKGROUND_TASKS.discard)
                await send_wechat_message(uid, "sign", "签到失败", f"{other_append_text}签到失败，签到已结束", icon="close-octagon", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"{sign_type}{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}自动签到失败，失败原因为“签到已结束”"}))
                await send_message(encrypt)
                LOGGER.info(f"{uid}-{name}:自动签到失败，失败原因为“签到已结束”")
            else:
                task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统签到失败通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[对应课程或班级] {na}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] {sign_type}{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {start_time}</p><p style=\"text-indent:2em\">[签到结束时间] {end_time}</p><p style=\"text-indent:2em\">[签到持续时间] {timelong}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[签到状态] {other_append_text}签到失败，{text}</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], f"学习通{sign_type}结果：签到失败"))
                BACKGROUND_TASKS.add(task)
                task.add_done_callback(BACKGROUND_TASKS.discard)
                await send_wechat_message(uid, "sign", "签到失败", f"{other_append_text}签到失败，{text}", icon="close-octagon", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"{sign_type}{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}自动签到失败，失败原因为“{text}”"}))
                await send_message(encrypt)
                LOGGER.info(f"{uid}-{name}:自动签到失败，失败原因为“{text}”")
            USER_LIST[uid]["sign_task_list"].pop(aid, None)
            await record_debug_log(f"{uid}-{name}:从签到任务列表中移除当前任务，aid:{aid}")
    except Exception:
        await record_error_log(traceback.format_exc(), False)


async def set_sign_location_info(aid, success_flag, address, longitude, latitude, msg):
    if success_flag:
        SIGN_INFO_DICT["location"][aid] = {"address": address, "longitude": longitude, "latitude": latitude}
    else:
        SIGN_INFO_DICT["fail_msg"][aid] = msg
    if LOCATION_LOCK.locked():
        LOCATION_LOCK.release()


async def set_sign_code_info(aid, success_flag, code, attack_time, msg):
    if success_flag:
        SIGN_INFO_DICT["code"][aid] = {"code": code, "attack_time": attack_time}
    else:
        SIGN_INFO_DICT["fail_msg"][aid] = msg
    if CODE_LOCK.locked():
        CODE_LOCK.release()


async def set_sign_validate_info(uid, aid, success_flag, validate):
    if success_flag:
        if SIGN_INFO_DICT["validate"].get(uid):
            SIGN_INFO_DICT["validate"][uid][aid] = {"validate": validate}
        else:
            SIGN_INFO_DICT["validate"][uid] = {aid: {"validate": validate}}
    if VALIDATE_LOCK.locked():
        VALIDATE_LOCK.release()


async def get_sign_location_info(uid, name, aid):
    for i in range(2):
        await LOCATION_LOCK.acquire()
        if i == 0:
            if SIGN_INFO_DICT["location"].get(aid):
                if LOCATION_LOCK.locked():
                    LOCATION_LOCK.release()
                return SIGN_INFO_DICT["location"][aid]
            else:
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "get_sign_location_info", "uid": uid, "name": name, "aid": aid}))
                await send_message(encrypt)
        else:
            if LOCATION_LOCK.locked():
                LOCATION_LOCK.release()
            if SIGN_INFO_DICT["location"].get(aid):
                return SIGN_INFO_DICT["location"][aid]
    return {"address": None, "longitude": None, "latitude": None, "msg": SIGN_INFO_DICT["fail_msg"].get(aid, "未知错误")}


async def get_sign_code_info(uid, name, aid):
    for i in range(2):
        await CODE_LOCK.acquire()
        if i == 0:
            if SIGN_INFO_DICT["code"].get(aid):
                if CODE_LOCK.locked():
                    CODE_LOCK.release()
                return SIGN_INFO_DICT["code"][aid]
            else:
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "get_sign_code_info", "uid": uid, "name": name, "aid": aid}))
                await send_message(encrypt)
        else:
            if CODE_LOCK.locked():
                CODE_LOCK.release()
            if SIGN_INFO_DICT["code"].get(aid):
                return SIGN_INFO_DICT["code"][aid]
    return {"code": None, "msg": SIGN_INFO_DICT["fail_msg"].get(aid, "未知错误")}


async def get_sign_validate_info(uid, name, aid) -> None | str:
    for i in range(2):
        await VALIDATE_LOCK.acquire()
        if i == 0:
            if SIGN_INFO_DICT["validate"].get(uid) and SIGN_INFO_DICT["validate"][uid].get(aid):
                if VALIDATE_LOCK.locked():
                    VALIDATE_LOCK.release()
                return SIGN_INFO_DICT["validate"][uid][aid]
            else:
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "get_sign_validate_info", "uid": uid, "name": name, "aid": aid}))
                await send_message(encrypt)
        else:
            if VALIDATE_LOCK.locked():
                VALIDATE_LOCK.release()
            if SIGN_INFO_DICT["validate"].get(uid) and SIGN_INFO_DICT["validate"][uid].get(aid):
                return SIGN_INFO_DICT["validate"][uid][aid]
    return {"validate": None}


def get_data_base64_encode(data):
    base64_encode_str = base64.b64encode(data)
    return base64_encode_str


def get_data_aes_decode(data):
    if data is None:
        return ""
    encrypted = get_data_base64_decode(data)
    cipher = AES.new(bytes(SERVER_KEY, "utf-8"), AES.MODE_CBC, bytes(SERVER_IV, "utf-8"))
    decrypted = cipher.decrypt(encrypted)
    return unpad(decrypted, AES.block_size).decode()


def get_data_aes_encode(data):
    raw = bytes(data, "utf-8")
    raw = pad(raw, AES.block_size)
    cipher = AES.new(bytes(SERVER_KEY, "utf-8"), AES.MODE_CBC, bytes(SERVER_IV, "utf-8"))
    encrypted = cipher.encrypt(raw)
    base_data = get_data_base64_encode(encrypted)
    return base_data.decode()


async def handle_sign_server_ws_message(message):
    try:
        data = await json_decode(message)
    except Exception:
        await record_error_log(traceback.format_exc())
        LOGGER.warning("无法解析服务端下发消息，请开启debug模式后运行查看下发消息内容")
        await sign_server_ws.close()
        return
    if data.get("system_message"):
        if data["result"] == 200:
            LOGGER.info(f'''节点上线成功，节点名称：{NODE_CONFIG["node"]["name"]}，节点uuid：{NODE_CONFIG["uuid"]}，节点密码：{NODE_CONFIG["node"]["password"] if NODE_CONFIG["node"]["password"] != "" else "无密码"}，限制使用人数：{f"{NODE_CONFIG['node']['limit']}人" if NODE_CONFIG["node"]["limit"] > 0 else "不限制人数"}，{"节点开启了夜间监控" if NODE_CONFIG["night_monitor"] else "节点关闭了夜间监控"}，可在在线自动签到系统中使用本节点''')
        else:
            LOGGER.warning(data["errormsg"])
            await asyncio.sleep(3)
            sys.exit()
    else:
        try:
            t = int(data["t"])
            if t+30 >= int(time.time()):
                data = await json_decode(await asyncio.to_thread(get_data_aes_decode, data["data"]))
                if data["type"] == "start_sign":
                    if not USER_LIST.get(data["uid"]):
                        message_lock = asyncio.Lock()
                        async with message_lock:
                            result = await person_sign(data["uid"], data["name"], data["username"], data["student_number"], data["password"], data["schoolid"], data["cookie"], data["port"], data["sign_type"], data["is_timing"], data["is_numing"], data["sign_num"], data["daterange"], data["set_address"], data["address"], data["longitude"], data["latitude"], data["set_objectId"], data["objectId"], data["bind_email"], data["email"], data["useragent"], data["deviceCode"], message_lock)
                            if result:
                                LOGGER.info(f"{data['uid']}-{data['name']}启动签到监控")
                                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"result": 1, "status": data["is_timing"], "type": "start_sign", "uid": data["uid"], "port": data["port"], "name": data["name"], "sign_type": data["sign_type"], "is_timing": data["is_timing"], "is_numing": data["is_numing"], "sign_num": data["sign_num"], "daterange": data["daterange"]}))
                                await send_message(encrypt)
                                await asyncio.sleep(1)
                            else:
                                await stop_reason(1, data["uid"], data["name"], data["bind_email"], data["email"])
                                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"result": 0, "type": "start_sign", "uid": data["uid"], "name": data["name"]}))
                                await send_message(encrypt)
                    else:
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"result": 1, "status": data["is_timing"], "type": "start_sign", "uid": data["uid"], "port": data["port"], "name": data["name"], "sign_type": data["sign_type"], "is_timing": data["is_timing"], "is_numing": data["is_numing"], "sign_num": data["sign_num"], "daterange": data["daterange"]}))
                        await send_message(encrypt)
                elif data["type"] == "update_sign":
                    if USER_LIST.get(data["uid"]):
                        await remove_sign_info(data["uid"], data["name"])
                    message_lock = asyncio.Lock()
                    async with message_lock:
                        result = await person_sign(data["uid"], data["name"], data["username"], data["student_number"], data["password"], data["schoolid"], data["cookie"], data["port"], data["sign_type"], data["is_timing"], data["is_numing"], data["sign_num"], data["daterange"], data["set_address"], data["address"], data["longitude"], data["latitude"], data["set_objectId"], data["objectId"], data["bind_email"], data["email"], data["useragent"], data["deviceCode"], message_lock)
                        if result:
                            LOGGER.info(f"{data['uid']}-{data['name']}启动签到监控")
                            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"result": 1, "type": "update_sign", "uid": data["uid"], "port": data["port"], "name": data["name"], "sign_type": data["sign_type"], "is_timing": data["is_timing"], "is_numing": data["is_numing"], "sign_num": data["sign_num"], "daterange": data["daterange"]}))
                            await send_message(encrypt)
                            await asyncio.sleep(1)
                        else:
                            await stop_reason(1, data["uid"], data["name"], data["bind_email"], data["email"])
                            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"result": 0, "type": "update_sign", "uid": data["uid"], "name": data["name"]}))
                            await send_message(encrypt)
                elif data["type"] == "online_start_sign":
                    task = asyncio.create_task(delete_cookies(data["uid_list"]))
                    BACKGROUND_TASKS.add(task)
                    task.add_done_callback(BACKGROUND_TASKS.discard)
                    diff = list(set(USER_LIST).difference(set(data["uid_list"])))
                    if diff:
                        for u in diff:
                            await remove_sign_info(u, USER_LIST[u]["name"])
                    for ll in data["sign_list"]:
                        if not USER_LIST.get(ll["uid"]):
                            message_lock = asyncio.Lock()
                            async with message_lock:
                                result = await person_sign(ll["uid"], ll["name"], ll["username"], ll["student_number"], ll["password"], ll["schoolid"], ll["cookie"], ll["port"], ll["sign_type"], ll["is_timing"], ll["is_numing"], ll["sign_num"], ll["daterange"], ll["set_address"], ll["address"], ll["longitude"], ll["latitude"], ll["set_objectId"], ll["objectId"], ll["bind_email"], ll["email"], ll["useragent"], ll["deviceCode"], message_lock)
                                if result:
                                    LOGGER.info(f"{ll['uid']}-{ll['name']}启动签到监控")
                                else:
                                    await stop_reason(1, ll["uid"], ll["name"], ll["bind_email"], ll["email"])
                                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "online_start_sign", "uid": ll["uid"], "name": ll["name"]}))
                                    await send_message(encrypt)
                    await asyncio.sleep(10)
                    for k, d in list(QRCODE_SIGN_DICT.items()):
                        if d["start_timestamp"]+86400 < int(time.time()):
                            uid = d["uid"]
                            name = d["name"]
                            await record_debug_log(f"{uid}-{name}:二维码签到发布时间超过24小时，取消签到")
                            lesson_name = d["lesson_name"]
                            activetype_append_text = d["activetype_append_text"]
                            signout_email_append_text = d["signout_email_append_text"]
                            signout_wechat_append_text = d["signout_wechat_append_text"]
                            task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统二维码签到取消通知]</p><p style=\"text-indent:2em\">[签到监测时间] {d['event_time2']}</p><p style=\"text-indent:2em\">[对应课程或班级] {lesson_name}</p><p style=\"text-indent:2em\">[签到活动名称] {d['name_one']}</p><p style=\"text-indent:2em\">[签到类型] {d['sign_type']}{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {d['start_time']}</p><p style=\"text-indent:2em\">[签到结束时间] {d['end_time']}</p><p style=\"text-indent:2em\">[签到持续时间] {d['timelong']}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[签到状态] 监测到签到发布时长超过24小时，系统将不再对当前二维码签到活动进行签到</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通二维码签到结果：签到取消"))
                            BACKGROUND_TASKS.add(task)
                            task.add_done_callback(BACKGROUND_TASKS.discard)
                            await send_wechat_message(uid, "sign", "签到取消", "监测到签到发布时长超过24小时，系统将不再对当前二维码签到活动进行签到", icon="error-circle", aid=d["aid"], coursename=lesson_name, activename=d["name_one"], start_time=d["start_time"], stop_time=d["wechat_end_time"], sign_info={"签到监测时间": d["event_time2"], "对应课程或班级": lesson_name, "签到活动名称": d["name_one"], "签到类型": f"{d['sign_type']}{activetype_append_text}", "签到开始时间": d["start_time"], "签到结束时间": d["end_time"], "签到持续时间": d["timelong"]} | signout_wechat_append_text, is_qrcode_sign=True)
                            event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}监测到课程或班级“{lesson_name}”的二维码签到发布时长超过24小时，系统将不再对当前二维码签到活动进行签到"}))
                            await send_message(encrypt)
                            LOGGER.info(f"{uid}-{name}:监测到课程或班级“{lesson_name}”的二维码签到发布时长超过24小时，系统将不再对当前二维码签到活动进行签到")
                            QRCODE_SIGN_DICT.pop(k, None)
                elif data["type"] == "stop_sign" or data["type"] == "force_stop_sign":
                    await remove_sign_info(data["uid"], data["name"])
                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": data["type"], "uid": data["uid"], "name": data["name"]}))
                    await send_message(encrypt)
                elif data["type"] == "update_sign_info":
                    if USER_LIST.get(data["uid"]):
                        USER_LIST[data["uid"]]["set_address"] = data["set_address"]
                        USER_LIST[data["uid"]]["address"] = data["address"]
                        USER_LIST[data["uid"]]["longitude"] = data["longitude"]
                        USER_LIST[data["uid"]]["latitude"] = data["latitude"]
                        USER_LIST[data["uid"]]["set_objectId"] = data["set_objectId"]
                        USER_LIST[data["uid"]]["objectId"] = data["objectId"]
                        USER_LIST[data["uid"]]["bind_email"] = data["bind_email"]
                        USER_LIST[data["uid"]]["email"] = data["email"]
                        USER_LIST[data["uid"]]["useragent"] = data["useragent"]
                        USER_LIST[data["uid"]]["deviceCode"] = data["deviceCode"]
                elif data["type"] == "push_qrcode_info":
                    task = asyncio.create_task(get_qrcode_for_ws(data["aid"], data["qrcode_info"], data["address"], data["longitude"], data["latitude"], data["from"], data["attend_list"]))
                    BACKGROUND_TASKS.add(task)
                    task.add_done_callback(BACKGROUND_TASKS.discard)
                elif data["type"] == "get_sign_location_info":
                    task = asyncio.create_task(set_sign_location_info(data["aid"], data["result"], data["address"], data["longitude"], data["latitude"], data.get("msg")))
                    BACKGROUND_TASKS.add(task)
                    task.add_done_callback(BACKGROUND_TASKS.discard)
                elif data["type"] == "get_sign_code_info":
                    task = asyncio.create_task(set_sign_code_info(data["aid"], data["result"], data["code"], data.get("attack_time"), data.get("msg")))
                    BACKGROUND_TASKS.add(task)
                    task.add_done_callback(BACKGROUND_TASKS.discard)
                elif data["type"] == "get_sign_validate_info":
                    task = asyncio.create_task(set_sign_validate_info(data["uid"], data["aid"], data["result"], data["validate"]))
                    BACKGROUND_TASKS.add(task)
                    task.add_done_callback(BACKGROUND_TASKS.discard)
                elif data["type"] == "get_log":
                    if os.path.isfile(os.path.join(REALPATH, "node_error_log.log")):
                        async with aiofiles.open(os.path.join(REALPATH, "node_error_log.log"), encoding="utf-8") as log_file:
                            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "node_log", "control_flag": "start", "log_type": "error"}))
                            await send_message(encrypt)
                            while True:
                                try:
                                    chunk = await log_file.read(50*1024)
                                    if not chunk:
                                        break
                                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "node_log", "control_flag": "progress", "log_type": "error", "data": chunk}))
                                    await send_message(encrypt)
                                    await asyncio.sleep(0.1)
                                except UnicodeDecodeError:
                                    continue
                            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "node_log", "control_flag": "end", "log_type": "error"}))
                            await send_message(encrypt)
                    else:
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "node_log", "control_flag": "start", "log_type": "error"}))
                        await send_message(encrypt)
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "node_log", "control_flag": "progress", "log_type": "error", "data": ""}))
                        await send_message(encrypt)
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "node_log", "control_flag": "end", "log_type": "error"}))
                        await send_message(encrypt)
                    if os.path.isfile(os.path.join(REALPATH, "node_debug_log.log")):
                        async with aiofiles.open(os.path.join(REALPATH, "node_debug_log.log"), encoding="utf-8") as log_file:
                            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "node_log", "control_flag": "start", "log_type": "debug"}))
                            await send_message(encrypt)
                            while True:
                                try:
                                    chunk = await log_file.read(100*1024)
                                    if not chunk:
                                        break
                                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "node_log", "control_flag": "progress", "log_type": "debug", "data": chunk}))
                                    await send_message(encrypt)
                                    await asyncio.sleep(0.1)
                                except UnicodeDecodeError:
                                    continue
                            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "node_log", "control_flag": "end", "log_type": "debug"}))
                            await send_message(encrypt)
                    else:
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "node_log", "control_flag": "start", "log_type": "debug"}))
                        await send_message(encrypt)
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "node_log", "control_flag": "progress", "log_type": "debug", "data": ""}))
                        await send_message(encrypt)
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "node_log", "control_flag": "end", "log_type": "debug"}))
                        await send_message(encrypt)
                    async with aiofiles.open(os.path.join(REALPATH, "node_error_log.log"), "w", encoding="utf-8") as log_file:
                        await log_file.close()
                    async with aiofiles.open(os.path.join(REALPATH, "node_debug_log.log"), "w", encoding="utf-8") as log_file:
                        await log_file.close()
                elif data["type"] == "upgrade_package":
                    await install()
        except Exception:
            await record_error_log(traceback.format_exc(), False)


async def sign_server_ws_monitor():
    global sign_server_ws
    task = asyncio.create_task(user_relogin_loop())
    BACKGROUND_TASKS.add(task)
    task.add_done_callback(BACKGROUND_TASKS.discard)
    task = asyncio.create_task(get_new_cookie_loop())
    BACKGROUND_TASKS.add(task)
    task.add_done_callback(BACKGROUND_TASKS.discard)
    task = asyncio.create_task(check_new_version_loop())
    BACKGROUND_TASKS.add(task)
    task.add_done_callback(BACKGROUND_TASKS.discard)
    interval = 10
    while True:
        try:
            async with websockets.connect("wss://cx-wss.waadri.top/othernode_server/websocket", ping_interval=10, ping_timeout=30, max_size=2**22, ssl=SSL_CONTEXT) as sign_server_ws:
                if LOCATION_LOCK.locked():
                    LOCATION_LOCK.release()
                if CODE_LOCK.locked():
                    CODE_LOCK.release()
                if VALIDATE_LOCK.locked():
                    VALIDATE_LOCK.release()
                interval = 10
                t = int(time.time())
                temp_list = []
                for k, d in list(QRCODE_SIGN_DICT.items()):
                    if d["sign_status"]:
                        QRCODE_SIGN_DICT.pop(k, None)
                    else:
                        temp_list += d["aid_list"]
                temp_list = list(set(temp_list))
                encrypt = await asyncio.to_thread(get_data_aes_encode, NODE_CONFIG["node"]["name"])
                data = {"t": t, "device_id": encrypt, "uuid": NODE_CONFIG["uuid"], "qrcode_sign_list": temp_list, "password": NODE_CONFIG["node"]["password"], "version": NODE_VERSION, "limit_number": NODE_CONFIG["node"]["limit"], "support_email": NODE_CONFIG["email"]["address"] != "", "night_monitor": NODE_CONFIG["night_monitor"], "token": "8e9c596504730a27c971941f84e82cd5"}
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode(data))
                async with MSG_SEND_LOCK:
                    await sign_server_ws.send(encrypt)
                async for message in sign_server_ws:
                    task = asyncio.create_task(handle_sign_server_ws_message(message))
                    BACKGROUND_TASKS.add(task)
                    task.add_done_callback(BACKGROUND_TASKS.discard)
        except (websockets.exceptions.ConnectionClosedOK, ConnectionRefusedError, websockets.exceptions.ConnectionClosedError, asyncio.exceptions.TimeoutError, OSError, websockets.exceptions.InvalidMessage, websockets.exceptions.InvalidStatus, websockets.exceptions.InvalidURI):
            if sign_server_ws is not None:
                await sign_server_ws.close()
            LOGGER.warning("节点掉线，尝试重新上线...")
            await asyncio.sleep(interval+random.uniform(0, 1))
            interval = min(interval*2, 60)
        except Exception:
            if sign_server_ws is not None:
                await sign_server_ws.close()
            await record_error_log(traceback.format_exc())
            LOGGER.warning("节点掉线，尝试重新上线...")
            await asyncio.sleep(interval+random.uniform(0, 1))
            interval = min(interval*2, 60)


async def get_data_url_unquote(data):
    url_unquote_str = unquote(data)
    return url_unquote_str


async def get_data_url_quote(data):
    url_quote_str = quote(data)
    return url_quote_str


async def qrcode_sign_handle(session, keys, name, schoolid, courseid, classid, aid, uid, qrcode_info, enc, location, source, lesson_name, is_numing, sign_num, event_time2, name_one, sign_type, start_time, end_time, wechat_end_time, timelong, header, devicecode, activetype_append_text, signout_email_append_text, signout_wechat_append_text):
    try:
        qrcode_sign_params = {
            "enc": enc,
            "name": name,
            "activeId": aid,
            "uid": uid,
            "clientip": "",
            "location": location,
            "latitude": "-1",
            "longitude": "-1",
            "fid": schoolid,
            "appType": "15",
            "deviceCode": devicecode,
            "vpProbability": "0",
            "vpStrategy": ""
        }
        ifNeedVCode = 0
        while True:
            try:
                await record_debug_log(f"{uid}-{name}:开始预签到")
                await get_request(uid, name, session, qrcode_info, header=header, json_type=False)
                await get_request(uid, name, session, "https://mobilelearn.chaoxing.com/newsign/preSign", {"courseId": courseid, "classId": classid, "activePrimaryId": aid, "general": 1, "sys": 1, "ls": 1, "appType": 15, "uid": uid, "ut": "s"}, header, json_type=False)
                txt = await get_request(uid, name, session, "https://mobilelearn.chaoxing.com/pptSign/stuSignajax", qrcode_sign_params, header, json_type=False)
                if txt == "请先登录再进行签到":
                    await record_debug_log(f"{uid}-{name}:二维码签到出现提示请先登录再进行签到，准备执行签到监控异常停止事件", False)
                    await stop_reason(1, uid, name, USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"])
                    return
                elif "validate" in txt:
                    await record_debug_log(f"{uid}-{name}:二维码签到出现validate，开始检查是否需要进行安全验证")
                    enc2 = txt.replace("validate_", "")
                    validate_text = await get_request(uid, name, session, "https://mobilelearn.chaoxing.com/widget/sign/pcStuSignController/checkIfValidate", {"DB_STRATEGY": "PRIMARY_KEY", "STRATEGY_PARA": "activeId", "activeId": aid, "puid": ""}, ignore_status_code=True)
                    if ifNeedVCode or validate_text["result"]:
                        await record_debug_log(f"{uid}-{name}:签到需要进行安全验证，aid:{aid}")
                        sign_validate_info = await get_sign_validate_info(uid, name, aid)
                        validate = sign_validate_info["validate"]
                        if validate is None:
                            if not QRCODE_SIGN_DICT[keys]["sign_status"]:
                                QRCODE_SIGN_DICT[keys]["sign_status"] = True
                                task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统签到失败通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[对应课程或班级] {lesson_name}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] {sign_type}{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {start_time}</p><p style=\"text-indent:2em\">[签到结束时间] {end_time}</p><p style=\"text-indent:2em\">[签到持续时间] {timelong}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[签到状态] 收到同班同学从{source}提交的签到二维码与指定位置信息，但由于签到需要进行安全验证且无法通过验证导致签到失败，系统将不再对当前二维码签到活动进行签到，请使用官方节点进行签到或自行登录学习通APP进行签到</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通二维码签到结果：签到失败"))
                                BACKGROUND_TASKS.add(task)
                                task.add_done_callback(BACKGROUND_TASKS.discard)
                                await send_wechat_message(uid, "sign", "签到失败", f"收到同班同学从{source}提交的签到二维码与指定位置信息，但由于签到需要进行安全验证且无法通过验证导致签到失败，系统将不再对当前二维码签到活动进行签到，请使用官方节点进行签到或自行登录学习通APP进行签到", icon="close-octagon", aid=aid, coursename=lesson_name, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": lesson_name, "签到活动名称": name_one, "签到类型": f"{sign_type}{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                                event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}收到同班同学从{source}提交的课程或班级“{lesson_name}”的签到二维码与指定位置信息，但由于签到需要进行安全验证且无法通过验证导致签到失败，系统将不再对当前二维码签到活动进行签到，请使用官方节点进行签到或自行登录学习通APP进行签到"}))
                                await send_message(encrypt)
                                LOGGER.info(f"{uid}-{name}:收到同班同学从{source}提交的课程或班级“{lesson_name}”的签到二维码与指定位置信息，但由于签到需要进行安全验证且无法通过验证导致签到失败，系统将不再对当前二维码签到活动进行签到")
                                return
                        qrcode_sign_params["validate"] = validate,
                        qrcode_sign_params["enc2"] = enc2
                        await record_debug_log(f"{uid}-{name}:安全验证已通过，开始预签到")
                    analysis_res = await get_request(uid, name, session, "https://mobilelearn.chaoxing.com/pptSign/analysis", {"vs": 1, "DB_STRATEGY": "RANDOM", "aid": aid}, header, json_type=False)
                    md5_pattern = re.compile(r"[a-f0-9]{32}")
                    md5_hash = md5_pattern.search(analysis_res)
                    if md5_hash:
                        md5_hash = md5_hash.group()
                        await get_request(uid, name, session, "https://mobilelearn.chaoxing.com/pptSign/analysis2", {"DB_STRATEGY": "RANDOM", "code": md5_hash}, header, json_type=False)
                    await asyncio.sleep(1)
                    txt = await get_request(uid, name, session, "https://mobilelearn.chaoxing.com/pptSign/stuSignajax", qrcode_sign_params, header, json_type=False)
                    if "validate" in txt and not ifNeedVCode:
                        await record_debug_log(f"{uid}-{name}:出现validate提示，尝试再次执行安全验证，aid:{aid}")
                        ifNeedVCode = 1
                        continue
                else:
                    await record_debug_log(f"{uid}-{name}:未出现validate提示，解析返回内容，aid:{aid}")
                break
            except Exception:
                await record_error_log(traceback.format_exc())
        if txt == "success":
            if not QRCODE_SIGN_DICT[keys]["sign_status"]:
                QRCODE_SIGN_DICT[keys]["sign_status"] = True
                task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统二维码签到成功通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[对应课程或班级] {lesson_name}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] {sign_type}{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {start_time}</p><p style=\"text-indent:2em\">[签到结束时间] {end_time}</p><p style=\"text-indent:2em\">[签到持续时间] {timelong}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[签到状态] 收到同班同学从{source}提交的签到二维码与指定位置信息，签到成功</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通二维码签到结果：签到成功"))
                BACKGROUND_TASKS.add(task)
                task.add_done_callback(BACKGROUND_TASKS.discard)
                await send_wechat_message(uid, "sign", "签到成功", f"收到同班同学从{source}提交的签到二维码与指定位置信息，签到成功", icon="check-circle", aid=aid, coursename=lesson_name, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": lesson_name, "签到活动名称": name_one, "签到类型": f"{sign_type}{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                USER_LIST[uid]["success_sign_num"] += 1
                event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}收到同班同学从{source}提交的课程或班级“{lesson_name}”的签到二维码与指定位置信息，自动签到成功"}))
                await send_message(encrypt)
                LOGGER.info(f"{uid}-{name}:收到同班同学从{source}提交的课程或班级“{lesson_name}”的签到二维码与指定位置信息，自动签到成功")
                if is_numing and USER_LIST[uid]["success_sign_num"] >= sign_num:
                    event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                    event_time2 = datetime.datetime.strftime(datetime.datetime.now(), "%Y-%m-%d %H:%M:%S")
                    task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统停止监控通知]</p><p style=\"text-indent:2em\">[监控停止时间] {event_time2}</p><p style=\"text-indent:2em\">[监控停止原因] 定次签到模式完成指定成功签到次数</p><p style=\"text-indent:2em\">如需重新启动签到监控请登录学习通在线自动签到系统并重新启动签到监控。</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通在线自动签到系统停止监控通知"))
                    BACKGROUND_TASKS.add(task)
                    task.add_done_callback(BACKGROUND_TASKS.discard)
                    await send_wechat_message(uid, "other", "学习通在线自动签到系统停止监控通知", {"监控停止时间": event_time2, "监控停止原因": "定次签到模式完成指定成功签到次数"}, "如需重新启动签到监控请登录学习通在线自动签到系统并重新启动签到监控", start_time=event_time2, reason="签到监控正常停止")
                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}定次签到模式已完成指定成功签到次数"}))
                    await send_message(encrypt)
                    LOGGER.info(f"{uid}-{name}:定次签到模式已完成指定成功签到次数")
                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "need_stop_sign", "uid": uid, "name": name}))
                    await send_message(encrypt)
        elif txt == "success2":
            if not QRCODE_SIGN_DICT[keys]["sign_status"]:
                QRCODE_SIGN_DICT[keys]["sign_status"] = True
                task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统二维码签到失败通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[对应课程或班级] {lesson_name}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] {sign_type}{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {start_time}</p><p style=\"text-indent:2em\">[签到结束时间] {end_time}</p><p style=\"text-indent:2em\">[签到持续时间] {timelong}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[签到状态] 收到同班同学从{source}提交的签到二维码与指定位置信息，但签到失败，失败原因为“签到已结束”，系统将不再对当前二维码签到活动进行签到</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通二维码签到结果：签到失败"))
                BACKGROUND_TASKS.add(task)
                task.add_done_callback(BACKGROUND_TASKS.discard)
                await send_wechat_message(uid, "sign", "签到失败", f"收到同班同学从{source}提交的签到二维码与指定位置信息，但签到失败，失败原因为“签到已结束”，系统将不再对当前二维码签到活动进行签到", icon="close-octagon", aid=aid, coursename=lesson_name, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": lesson_name, "签到活动名称": name_one, "签到类型": f"{sign_type}{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}收到同班同学从{source}提交的课程或班级“{lesson_name}”的签到二维码与指定位置信息，但学习通提示“签到已结束”，系统将不再对当前二维码签到活动进行签到"}))
                await send_message(encrypt)
                LOGGER.info(f"{uid}-{name}:收到同班同学从{source}提交的课程或班级“{lesson_name}”的签到二维码与指定位置信息，但学习通提示“签到已结束”，系统将不再对当前二维码签到活动进行签到")
        elif txt == "您已签到过了" or txt == "同一设备不允许重复签到" or txt == "非本班学生":
            txt2 = txt
            if txt2 == "非本班学生":
                txt2 = f"您{txt2}"
            if not QRCODE_SIGN_DICT[keys]["sign_status"]:
                QRCODE_SIGN_DICT[keys]["sign_status"] = True
                task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统二维码签到失败通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[对应课程或班级] {lesson_name}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] {sign_type}{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {start_time}</p><p style=\"text-indent:2em\">[签到结束时间] {end_time}</p><p style=\"text-indent:2em\">[签到持续时间] {timelong}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[签到状态] 收到同班同学从{source}提交的签到二维码与指定位置信息，但签到失败，失败原因为“{txt2}”，系统将不再对当前二维码签到活动进行签到</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通二维码签到结果：签到失败"))
                BACKGROUND_TASKS.add(task)
                task.add_done_callback(BACKGROUND_TASKS.discard)
                await send_wechat_message(uid, "sign", "签到失败", f"收到同班同学从{source}提交的签到二维码与指定位置信息，但签到失败，失败原因为“{txt2}”，系统将不再对当前二维码签到活动进行签到", icon="close-octagon", aid=aid, coursename=lesson_name, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": lesson_name, "签到活动名称": name_one, "签到类型": f"{sign_type}{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}收到同班同学从{source}提交的课程或班级“{lesson_name}”的签到二维码与指定位置信息，但学习通提示“{txt}”，系统将不再对当前二维码签到活动进行签到"}))
                await send_message(encrypt)
                LOGGER.info(f"{uid}-{name}:收到同班同学从{source}提交的课程或班级“{lesson_name}”的签到二维码与指定位置信息，但学习通提示“{txt}”，系统将不再对当前二维码签到活动进行签到")
        else:
            if txt == "errorLocation1" or txt == "errorLocation2":
                await send_wechat_message(uid, "sign", "签到尝试失败", f"收到同班同学从{source}提交的签到二维码与指定位置信息，但签到失败，失败原因为“{txt}”，您所选位置可能不在教师指定签到位置范围内，请让同班同学使用微信小程序重新选择指定位置并扫描未过期的签到二维码，扫描后系统将继续尝试签到", icon="error-circle", aid=aid, coursename=lesson_name, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": lesson_name, "签到活动名称": name_one, "签到类型": f"{sign_type}{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}收到同班同学从{source}提交的课程或班级“{lesson_name}”的签到二维码与指定位置信息，但自动签到失败，失败原因为“{txt}”，您所选位置可能不在教师指定签到位置范围内，请让同班同学使用微信小程序重新选择指定位置并扫描未过期的签到二维码，扫描后系统将继续尝试签到"}))
                await send_message(encrypt)
            else:
                await send_wechat_message(uid, "sign", "签到尝试失败", f"收到同班同学从{source}提交的签到二维码与指定位置信息，但签到失败，失败原因为“{txt}”，签到二维码可能已过期，请让同班同学使用微信小程序重新扫描未过期的签到二维码，扫描后系统将继续尝试签到", icon="error-circle", aid=aid, coursename=lesson_name, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": lesson_name, "签到活动名称": name_one, "签到类型": f"{sign_type}{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text)
                event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}收到同班同学从{source}提交的课程或班级“{lesson_name}”的签到二维码与指定位置信息，但自动签到失败，失败原因为“{txt}”，签到二维码可能已过期，请让同班同学使用微信小程序重新扫描未过期的签到二维码，扫描后系统将继续尝试签到"}))
                await send_message(encrypt)
            LOGGER.info(f"{uid}-{name}:收到同班同学从{source}提交的课程或班级“{lesson_name}”的签到二维码与指定位置信息，但自动签到失败，失败原因为“{txt}”")
    except Exception:
        await record_error_log(traceback.format_exc(), False)


async def get_message(ws, message, uid, name, schoolid, sign_type, is_numing, sign_num, tid):
    try:
        chatid = await getchatid(message)
        if chatid is None:
            return
        sessonend = 11
        while True:
            index = sessonend
            if chr(message[index]) != b"\x22".decode():
                index += 1
                if chr(message[index]) != b"\x22".decode():
                    index += 1
                    break
                else:
                    index += 1
            else:
                index += 1
            sessonend = message[index]+(message[index+1]-1)*0x80+index+2
            index += 2
            if sessonend < 0 or chr(message[index]).encode() != b"\x08":
                index += 1
                break
            else:
                index += 1
            temp = await asyncio.to_thread(get_data_base64_encode, await buildreleasesession(chatid, message[index:index+9]))
            await ws.send(await json_encode([temp.decode()]))
            if not NODE_CONFIG["night_monitor"] and datetime.datetime.now().time() < datetime.time(6):
                return
            index += 10
            att = await getattachment(message, index, sessonend)
            if att is not None:
                if att["attachmentType"] == 15 and att["att_chat_course"].get("atype") is not None and (att["att_chat_course"]["atype"] == 2 or att["att_chat_course"]["atype"] == 0 or att["att_chat_course"]["atype"] == 74) and att["att_chat_course"]["type"] == 1 and att["att_chat_course"]["aid"] != 0:
                    await record_debug_log(f"{uid}-{name}:收到签到消息，活动ID:{att['att_chat_course']['aid']}")
                    aid = str(att["att_chat_course"]["aid"])
                    if aid not in USER_LIST[uid]["signed_in_list"]:
                        await record_debug_log(f"{uid}-{name}:此活动不在已签到活动列表中，准备签到，活动ID:{aid}")
                        USER_LIST[uid]["signed_in_list"].append(aid)
                        try:
                            if "mobilelearn.chaoxing.com/newsign/preSign" in att["att_chat_course"]["url"] or "mobilelearn.chaoxing.com/widget/attendanceSign/student/studentSign" in att["att_chat_course"]["url"]:
                                await record_debug_log(f"{uid}-{name}:此签到为课程或班级签到，活动ID:{aid}")
                                if await check_sign_type(uid, name, aid, sign_type):
                                    await record_debug_log(f"{uid}-{name}:此签到符合用户所设置的签到类型，开始签到，活动ID:{aid}")
                                    coursename = att["att_chat_course"]["courseInfo"].get("coursename", "未知课程")
                                    event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}收到来自课程或班级“{coursename}”的签到活动，签到活动名称为“{att['att_chat_course']['title']}”"}))
                                    await send_message(encrypt)
                                    LOGGER.info(f"{uid}-{name}:收到来自课程或班级“{coursename}”的签到活动，签到活动名称为“{att['att_chat_course']['title']}”")
                                    USER_LIST[uid]["sign_task_list"][aid] = asyncio.create_task(signt(uid, name, att["att_chat_course"]["courseInfo"]["courseid"], att["att_chat_course"]["courseInfo"]["classid"], aid, schoolid, is_numing, sign_num, att["att_chat_course"]["title"], coursename, 1, tid))
                            elif att["att_chat_course"]["atype"] == 2:
                                await record_debug_log(f"{uid}-{name}:此签到为群聊签到，活动ID:{aid}")
                                if "7" in sign_type:
                                    await record_debug_log(f"{uid}-{name}:此签到符合用户所设置的签到类型，开始签到，活动ID:{aid}")
                                    event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}收到来自群聊的签到活动，签到活动名称为“{att['att_chat_course']['title']}”"}))
                                    await send_message(encrypt)
                                    LOGGER.info(f"{uid}-{name}:收到来自群聊的签到活动，签到活动名称为“{att['att_chat_course']['title']}”")
                                    USER_LIST[uid]["sign_task_list"][aid] = asyncio.create_task(group_signt(uid, name, aid, is_numing, sign_num, att["att_chat_course"]["title"]))
                                else:
                                    await record_debug_log(f"{uid}-{name}:未开启该类型的自动签到，取消签到")
                                    event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}监测到签到类型为群聊签到的签到活动，由于您关闭了该类型的自动签到，因此取消签到"}))
                                    await send_message(encrypt)
                                    LOGGER.info(f"{uid}-{name}:监测到签到类型为群聊签到的签到活动，由于用户关闭了该类型的自动签到，因此取消签到")
                        except Exception:
                            LOGGER.warning(f"{uid}-{name}:解析时出错")
                            await record_error_log(traceback.format_exc())
                            await record_error_log(await json_encode(att))
            break
    except Exception:
        await record_error_log(traceback.format_exc(), False)


@retry(wait=wait_fixed(2))
async def getpptactiveinfo(uid, name, activeid):
    if USER_LIST.get(uid):
        res = await get_request(uid, name, USER_LIST[uid]["session"], "https://mobilelearn.chaoxing.com/v2/apis/active/getPPTActiveInfo", {"activeId": activeid}, need_cookie=True)
    else:
        return False
    if not res["result"]:
        if res["errorMsg"] == "no data":
            await record_error_log(await json_encode(res))
            await record_error_log(f"{uid}-{name}:签到信息获取失败，等待2秒后重试")
            raise ValueError
        await record_debug_log(f"{uid}-{name}:签到信息获取失败，准备执行签到监控异常停止事件", False)
        await record_debug_log(await json_encode(res), False)
        await record_debug_log(await json_encode(res["sign_cookie"]), False)
        task = asyncio.create_task(stop_reason(1, uid, name, USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"]))
        BACKGROUND_TASKS.add(task)
        task.add_done_callback(BACKGROUND_TASKS.discard)
        return False
    else:
        return res


async def check_sign_type(uid, name, activeid, sign_type):
    res = await getpptactiveinfo(uid, name, activeid)
    if res is False:
        return False
    createuid = res["data"]["createuid"]
    if uid == createuid:
        await record_debug_log(f"{uid}-{name}:该签到为当前用户发放，取消签到")
        event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}监测到您发放的课程或班级签到活动，取消签到"}))
        await send_message(encrypt)
        LOGGER.info(f"{uid}-{name}:监测到用户发放的课程或班级签到活动，取消签到")
        return False
    if res["data"]["otherId"] == 0:
        if res["data"]["ifphoto"] == 1:
            this_sign_type = "1"
            sign_type_name = "拍照签到"
        else:
            this_sign_type = "0"
            sign_type_name = "普通签到"
    elif res["data"]["otherId"] == 2:
        this_sign_type = "2"
        sign_type_name = "二维码签到"
    elif res["data"]["otherId"] == 3:
        this_sign_type = "3"
        sign_type_name = "手势签到"
    elif res["data"]["otherId"] == 4:
        if res["data"]["ifopenAddress"] == 1:
            this_sign_type = "6"
            sign_type_name = "指定位置签到"
        else:
            this_sign_type = "4"
            sign_type_name = "普通位置签到"
    elif res["data"]["otherId"] == 5:
        this_sign_type = "5"
        sign_type_name = "签到码签到"
    else:
        await record_debug_log(f"{uid}-{name}:无法识别的签到类型", False)
        return False
    if this_sign_type in sign_type:
        return True
    else:
        await record_debug_log(f"{uid}-{name}:未开启该类型的自动签到，取消签到")
        event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}监测到签到类型为{sign_type_name}的签到活动，由于您关闭了该类型的自动签到，因此取消签到"}))
        await send_message(encrypt)
        LOGGER.info(f"{uid}-{name}:监测到签到类型为{sign_type_name}的签到活动，由于用户关闭了该类型的自动签到，因此取消签到")
        return False


async def group_signt(uid, name, aid, is_numing, sign_num, name_one):
    try:
        event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
        event_time2 = datetime.datetime.strftime(datetime.datetime.now(), "%Y-%m-%d %H:%M:%S")
        start_timestamp = int(time.time())
        start_time = datetime.datetime.strftime(datetime.datetime.fromtimestamp(start_timestamp), "%Y-%m-%d %H:%M:%S")
        wechat_end_time = datetime.datetime.strftime(datetime.datetime.fromtimestamp(start_timestamp+86400), "%Y-%m-%d %H:%M:%S")
        await send_wechat_message(uid, "sign", "发现签到", "监控到签到活动，准备签到", icon="time", aid=aid, coursename="群聊", activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "签到活动名称": name_one, "签到类型": "群聊签到"}, is_group_sign=True)
        sign_data = {
            "activeId": aid,
            "uid": uid,
            "clientip": "10.0.85.109",
            "useragent": USER_LIST[uid]["header"]["User-Agent"],
            "latitude": USER_LIST[uid]["latitude"],
            "longitude": USER_LIST[uid]["longitude"],
            "fid": USER_LIST[uid]["schoolid"],
            "objectId": USER_LIST[uid]["objectId"],
            "address": USER_LIST[uid]["address"],
            "ifTiJiao": "1"
        }
        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}等待10秒后开始自动签到"}))
        await send_message(encrypt)
        LOGGER.info(f"{uid}-{name}:等待10秒后开始自动签到")
        await asyncio.sleep(10)
        info = await get_request(uid, name, USER_LIST[uid]["session"], "https://mobilelearn.chaoxing.com/sign/stuSignajax", sign_data, USER_LIST[uid]["header"], json_type=False)
        if info == "success":
            USER_LIST[uid]["success_sign_num"] += 1
            await send_email(uid, name, f"<p>[学习通在线自动签到系统签到成功通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] 群聊签到</p><p style=\"text-indent:2em\">[签到状态] 签到成功</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通群聊签到结果：签到成功")
            await send_wechat_message(uid, "sign", "签到成功", "签到成功", icon="check-circle", aid=aid, coursename="群聊", activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "签到活动名称": name_one, "签到类型": "群聊签到"}, is_group_sign=True)
            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}自动签到成功"}))
            await send_message(encrypt)
            LOGGER.info(f"{uid}-{name}:自动签到成功")
            if is_numing and USER_LIST[uid]["success_sign_num"] >= sign_num:
                event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                event_time2 = datetime.datetime.strftime(datetime.datetime.now(), "%Y-%m-%d %H:%M:%S")
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}定次签到模式已完成指定成功签到次数"}))
                await send_message(encrypt)
                await send_email(uid, name, f"<p>[学习通在线自动签到系统停止监控通知]</p><p style=\"text-indent:2em\">[监控停止时间] {event_time2}</p><p style=\"text-indent:2em\">[监控停止原因] 定次签到模式完成指定成功签到次数</p><p style=\"text-indent:2em\">如需重新启动签到监控请登录学习通在线自动签到系统并重新启动签到监控。</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通在线自动签到系统停止监控通知")
                await send_wechat_message(uid, "other", "学习通在线自动签到系统停止监控通知", {"监控停止时间": event_time2, "监控停止原因": "定次签到模式完成指定成功签到次数"}, "如需重新启动签到监控请登录学习通在线自动签到系统并重新启动签到监控", start_time=event_time2, reason="签到监控正常停止")
                LOGGER.info(f"{uid}-{name}:定次签到模式完成指定成功签到次数")
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "need_stop_sign", "uid": uid, "name": name}))
                await send_message(encrypt)
        elif info == "false":
            task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统签到失败通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] 群聊签到</p><p style=\"text-indent:2em\">[签到状态] 签到失败，您已签到过了</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通群聊签到结果：签到失败"))
            BACKGROUND_TASKS.add(task)
            task.add_done_callback(BACKGROUND_TASKS.discard)
            await send_wechat_message(uid, "sign", "签到失败", "签到失败，您已签到过了", icon="close-octagon", aid=aid, coursename="群聊", activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "签到活动名称": name_one, "签到类型": "群聊签到"}, is_group_sign=True)
            event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}自动签到失败，失败原因为“您已签到过了”"}))
            await send_message(encrypt)
            LOGGER.info(f"{uid}-{name}:自动签到失败，失败原因为“您已签到过了”")
        else:
            task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统签到失败通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] 群聊签到</p><p style=\"text-indent:2em\">[签到状态] 签到失败，{info}</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通群聊签到结果：签到失败"))
            BACKGROUND_TASKS.add(task)
            task.add_done_callback(BACKGROUND_TASKS.discard)
            await send_wechat_message(uid, "sign", "签到失败", f"签到失败，{info}", icon="close-octagon", aid=aid, coursename="群聊", activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "签到活动名称": name_one, "签到类型": "群聊签到"}, is_group_sign=True)
            event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}自动签到失败，失败原因为“{info}”"}))
            await send_message(encrypt)
            LOGGER.info(f"{uid}-{name}:自动签到失败，失败原因为“{info}”")
        USER_LIST[uid]["sign_task_list"].pop(aid, None)
        await record_debug_log(f"{uid}-{name}:从签到任务列表中移除当前任务，aid:{aid}")
    except Exception:
        await record_error_log(traceback.format_exc(), False)


async def getattachment(byte, start, end):
    try:
        start = await bytes_index_of(byte, BYTESATTACHMENT, start, end)
        if start == -1:
            return None
        start += len(BYTESATTACHMENT)
        length = byte[start]+(byte[start+1]-1)*0x80
        start += 2
        s = start
        start += length
        e = start
        try:
            j = await json_decode(byte[s:e].decode("utf-8"))
        except UnicodeDecodeError:
            await record_error_log(byte[s:e].decode("utf-8", errors='backslashreplace'), False)
            return None
        return None if start > end else j
    except Exception:
        await record_error_log(traceback.format_exc(), False)
        return None


async def bytes_index_of(byte, value, start, end):
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
    except Exception:
        await record_error_log(traceback.format_exc(), False)
        return -1


async def buildreleasesession(chatid, session):
    return bytearray([0x08, 0x00, 0x40, 0x00, 0x4a])+chr(len(chatid)+38).encode()+b"\x10"+session+bytearray([0x1a, 0x29, 0x12])+chr(len(chatid)).encode()+chatid.encode("utf-8")+BYTESEND+bytearray([0x58, 0x00])


async def first_get_taskinfo(ws, message, uid, name):
    try:
        if USER_LIST[uid]["first_check"]:
            event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}开始清理websockets未读消息，此过程可能需要几分钟，请耐心等待"}))
            await send_message(encrypt)
            LOGGER.info(f"{uid}-{name}:开始清理websockets未读消息")
        if await getchatid(message):
            chatid_list = re.findall(rb"\x12-\n\)\x12\x0f(\d+)\x1a\x16conference.easemob.com\x10", message)
            for ID in chatid_list:
                temp = await asyncio.to_thread(get_data_base64_encode, b"\x08\x00@\x00J+\x1a)\x12\x0f"+ID+b"\x1a\x16conference.easemob.comX\x00")
                await ws.send(await json_encode([temp.decode()]))
            if chatid_list:
                await asyncio.sleep(10)
                await ws.close()
        if USER_LIST[uid]["first_check"]:
            event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}websockets未读消息清理完成，正在监听新的签到活动"}))
            await send_message(encrypt)
            LOGGER.info(f"{uid}-{name}:websockets未读消息清理完成，正在监听新的签到活动")
            USER_LIST[uid]["first_check"] = False
    except Exception:
        await record_error_log(traceback.format_exc(), False)


async def getchatid(byte):
    try:
        index = await bytes_last_index_of(byte, BYTESEND)
        if index == -1:
            return None
        i = byte[:index].rfind(bytes([0x12]))
        if i == -1:
            return None
        length = byte[i+1]
        return byte[i+2:index].decode("utf-8") if i+2+length == index else None
    except Exception:
        await record_error_log(traceback.format_exc(), False)
        return None


async def bytes_last_index_of(byte, value):
    try:
        length = len(value)
        len_bytes = len(byte)
        if length == 0 or len_bytes == 0:
            return -1
        last = value[-1]
        for i in range(len_bytes-1, -1, -1):
            if byte[i] != last:
                continue
            is_return = True
            for j in range(length-2, -1, -1):
                if byte[i-length+j+1] == value[j]:
                    continue
                is_return = False
                break
            if is_return:
                return i-length+1
        return -1
    except Exception:
        await record_error_log(traceback.format_exc(), False)
        return -1


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
        temp = await asyncio.to_thread(get_data_base64_encode, mess2.encode())
        try:
            await ws.send(await json_encode([temp.decode()]))
        except websockets.exceptions.ConnectionClosedOK:
            await ws.close()
    except Exception:
        await record_error_log(traceback.format_exc(), False)


async def ws_login(ws, uid, name, imusername, impassword):
    try:
        res = await post_request(uid, name, USER_LIST[uid]["session"], "https://a1-vip6.easemob.com/cx-dev/cxstudy/token", {"grant_type": "password", "username": imusername, "password": impassword}, True)
        if res["status_code"] == 200:
            usuid = res["user"]["username"]
            im_token = res["access_token"]
            deviceid = f"1{uid}{usuid}"[:13]
            temp = await asyncio.to_thread(get_data_base64_encode, b"\x08\x00\x12"+chr(52+len(usuid)).encode()+b"\x0a\x0e"+"cx-dev#cxstudy".encode()+b"\x12"+chr(len(usuid)).encode()+usuid.encode()+b"\x1a\x0b"+"easemob.com".encode()+b"\x22\x13"+f"webim_{deviceid}".encode()+b"\x1a\x85\x01"+"$t$".encode()+im_token.encode()+b"\x40\x03\x4a\xc0\x01\x08\x10\x12\x05\x33\x2e\x30\x2e\x30\x28\x00\x30\x00\x4a\x0d"+deviceid.encode()+b"\x62\x05\x77\x65\x62\x69\x6d\x6a\x13\x77\x65\x62\x69\x6d\x5f"+deviceid.encode()+b"\x72\x85\x01\x24\x74\x24"+im_token.encode()+b"\x50\x00\x58\x00")
            try:
                await ws.send(await json_encode([temp.decode()]))
            except (websockets.exceptions.ConnectionClosedOK, websockets.exceptions.ConnectionClosedError):
                await ws.close()
        else:
            await record_debug_log(f"{uid}-{name}:登录IM失败，无法获取token，准备执行签到监控异常停止事件", False)
            task = asyncio.create_task(stop_reason(1, uid, name, USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"]))
            BACKGROUND_TASKS.add(task)
            task.add_done_callback(BACKGROUND_TASKS.discard)
    except websockets.exceptions.ConnectionClosedError:
        await ws.close()
    except Exception:
        await record_error_log(traceback.format_exc(), False)


async def remove_sign_info(uid, name):
    try:
        for k, v in list(QRCODE_SIGN_DICT.items()):
            if uid == v["uid"]:
                await record_debug_log(f"{uid}-{name}:删除二维码签到待签队列中的数据:{await json_encode(v)}")
                QRCODE_SIGN_DICT.pop(k, None)
        if USER_LIST.get(uid):
            if 1 in USER_LIST[uid]["port"] and USER_LIST[uid].get("ws_sign_heartbeat") and not USER_LIST[uid]["ws_sign_heartbeat"].done():
                await record_debug_log(f"{uid}-{name}:取消心跳检查")
                USER_LIST[uid]["ws_sign_heartbeat"].cancel()
            for sk, sv in list(USER_LIST[uid]["sign_task_list"].items()):
                if not sv.done():
                    await record_debug_log(f"{uid}-{name}:取消签到任务，aid:{sk}")
                    sv.cancel()
            for m in USER_LIST[uid]["main_sign_task"]:
                if not m.done():
                    await record_debug_log(f"{uid}-{name}:取消签到检查主循环任务")
                    m.cancel()
            await record_debug_log(f"{uid}-{name}:关闭用户session")
            await USER_LIST[uid]["session"].close()
            LOGGER.info(f"{uid}-{name}停止签到监控")
            await record_debug_log(f"{uid}-{name}:从用户列表中删除用户信息")
            USER_LIST.pop(uid, None)
    except Exception:
        await record_error_log(traceback.format_exc(), False)


async def check_monitor_time(uid, name, schoolid, sign_type, is_timing, is_numing, sign_num, daterange, lock, port, tid, imusername, impassword):
    try:
        if is_timing:
            temp_time = []
            for d in daterange:
                temp_time.append(f"{datetime.datetime.fromtimestamp(d[0]).strftime('%Y-%m-%d %H:%M:%S')}-{datetime.datetime.fromtimestamp(d[1]).strftime('%Y-%m-%d %H:%M:%S')}")
            event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}定时签到模式已启用，系统将在{'、'.join(temp_time)}启动签到监控"}))
            async with lock:
                await send_message(encrypt)
            LOGGER.info(f"{uid}-{name}:定时签到模式已启用，系统将在{'、'.join(temp_time)}启动签到监控")
            task = asyncio.create_task(check_sign_time(uid, name, schoolid, sign_type, is_numing, sign_num, daterange, port, tid, imusername, impassword))
            BACKGROUND_TASKS.add(task)
            task.add_done_callback(BACKGROUND_TASKS.discard)
        else:
            if len(port) == 2:
                event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}当前使用双接口进行签到监控"}))
                async with lock:
                    await send_message(encrypt)
                LOGGER.info(f"{uid}-{name}:当前使用双接口进行签到监控")
            if 1 in port:
                async with lock:
                    USER_LIST[uid]["main_sign_task"].append(asyncio.create_task(ws_connect(uid, name, schoolid, sign_type, is_numing, sign_num, tid, imusername, impassword)))
            if 2 in port or 3 in port or 4 in port:
                async with lock:
                    USER_LIST[uid]["main_sign_task"].append(asyncio.create_task(start_sign(uid, name, schoolid, sign_type, is_numing, sign_num, port, tid, imusername, impassword)))
    except Exception:
        await record_error_log(traceback.format_exc(), False)


async def ws_connect(uid, name, schoolid, sign_type, is_numing, sign_num, tid, imusername, impassword):
    try:
        first_start = True
        ws = None
        interval = 10
        is_night = False
        while True:
            try:
                ws_str1 = str(int(random.random()*1000))
                ws_str2 = ''.join(random.choices("abcdefghijklmnopqrstuvwxyz012345", k=8))
                async with websockets.connect(f"wss://im-api-vip6-v2.easemob.com/ws/{ws_str1}/{ws_str2}/websocket", ping_interval=None, ping_timeout=None, ssl=SSL_CONTEXT) as ws:
                    USER_LIST[uid]["ws"] = ws
                    if USER_LIST.get(uid):
                        USER_LIST[uid]["ws_heartbeat_time"] = time.time()
                        USER_LIST[uid]["ws_sign_heartbeat"] = asyncio.create_task(check_ws_heartbeat_message_time(ws, uid))
                    else:
                        return
                    interval = 10
                    async for message in ws:
                        if USER_LIST.get(uid):
                            USER_LIST[uid]["ws_heartbeat_time"] = time.time()
                        else:
                            return
                        if not NODE_CONFIG["night_monitor"]:
                            now = datetime.datetime.now().time()
                            if now < datetime.time(6) and not is_night:
                                await record_debug_log(f"{uid}-{name}:暂停使用接口1进行签到监控")
                                is_night = True
                                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')}接口1每日0时至6时暂停签到监控"}))
                                await send_message(encrypt)
                            elif now >= datetime.time(6) and is_night:
                                await record_debug_log(f"{uid}-{name}:继续使用接口1进行签到监控")
                                is_night = False
                                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{datetime.datetime.strftime(datetime.datetime.now(), '[%Y-%m-%d %H:%M:%S]')}接口1继续进行签到监控"}))
                                await send_message(encrypt)
                        if message == "o":
                            await record_debug_log(f"{uid}-{name}:开始登录IM")
                            task = asyncio.create_task(ws_login(ws, uid, name, imusername, impassword))
                            BACKGROUND_TASKS.add(task)
                            task.add_done_callback(BACKGROUND_TASKS.discard)
                        elif message[0] == "a":
                            mess = (await json_decode(message[1:]))[0]
                            mess = await asyncio.to_thread(get_data_base64_decode, mess)
                            if len(mess) < 5:
                                return
                            if mess[:5] == b"\x08\x00\x40\x02\x4a":
                                await record_debug_log(f"{uid}-{name}:开始获取消息详情")
                                task = asyncio.create_task(get_taskinfo(ws, mess))
                                BACKGROUND_TASKS.add(task)
                                task.add_done_callback(BACKGROUND_TASKS.discard)
                            elif mess[:5] == b"\x08\x00\x40\x01\x4a":
                                await record_debug_log(f"{uid}-{name}:开始获取未读消息详情")
                                task = asyncio.create_task(first_get_taskinfo(ws, mess, uid, name))
                                BACKGROUND_TASKS.add(task)
                                task.add_done_callback(BACKGROUND_TASKS.discard)
                            elif mess[:5] == b"\x08\x00@\x03J":
                                await record_debug_log(f"{uid}-{name}:IM登录成功")
                                if USER_LIST.get(uid):
                                    if first_start:
                                        event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}与学习通websockets服务器连接成功"}))
                                        await send_message(encrypt)
                                        LOGGER.info(f"{uid}-{name}:与学习通websockets服务器连接成功")
                                        first_start = False
                                    await ws.send(await json_encode(["CABAAVgA"]))
                                else:
                                    return
                            else:
                                await record_debug_log(f"{uid}-{name}:开始解析消息内容")
                                task = asyncio.create_task(get_message(ws, mess, uid, name, schoolid, sign_type, is_numing, sign_num, tid))
                                BACKGROUND_TASKS.add(task)
                                task.add_done_callback(BACKGROUND_TASKS.discard)
            except (websockets.exceptions.ConnectionClosedOK, websockets.exceptions.ConnectionClosedError, socket.gaierror, ConnectionResetError, TimeoutError, asyncio.exceptions.TimeoutError, OSError, websockets.exceptions.InvalidMessage):
                if ws is not None:
                    await ws.close()
                if USER_LIST.get(uid) and USER_LIST[uid].get("ws_sign_heartbeat") and not USER_LIST[uid]["ws_sign_heartbeat"].done():
                    USER_LIST[uid]["ws_sign_heartbeat"].cancel()
                await asyncio.sleep(interval+random.uniform(0, 1))
                interval = min(interval*2, 60)
            except Exception:
                if ws is not None:
                    await ws.close()
                await record_error_log(traceback.format_exc())
                if USER_LIST.get(uid) and USER_LIST[uid].get("ws_sign_heartbeat") and not USER_LIST[uid]["ws_sign_heartbeat"].done():
                    USER_LIST[uid]["ws_sign_heartbeat"].cancel()
                await asyncio.sleep(interval+random.uniform(0, 1))
                interval = min(interval*2, 60)
    except Exception:
        await record_error_log(traceback.format_exc(), False)


async def check_ws_heartbeat_message_time(ws, uid):
    try:
        while True:
            if USER_LIST.get(uid) is None or (USER_LIST[uid].get("ws_heartbeat_time") and time.time() > USER_LIST[uid]["ws_heartbeat_time"]+60) or USER_LIST[uid]["ws"] != ws:
                await ws.close()
                break
            await asyncio.sleep(1)
    except Exception:
        await record_error_log(traceback.format_exc(), False)


async def check_sign_time(uid, name, schoolid, sign_type, is_numing, sign_num, daterange, port, tid, imusername, impassword):
    try:
        if len(port) == 2:
            event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}当前使用双接口进行签到监控"}))
            await send_message(encrypt)
            LOGGER.info(f"{uid}-{name}:当前使用双接口进行签到监控")
        for d in range(len(daterange)):
            if int(time.time()) > daterange[d][1]:
                continue
            while daterange[d][0] > int(time.time()):
                if USER_LIST.get(uid):
                    await asyncio.sleep(1)
                else:
                    return
            if 1 in port:
                USER_LIST[uid]["main_sign_task"].append(asyncio.create_task(ws_connect(uid, name, schoolid, sign_type, is_numing, sign_num, tid, imusername, impassword)))
            if 2 in port or 3 in port or 4 in port:
                USER_LIST[uid]["main_sign_task"].append(asyncio.create_task(start_sign(uid, name, schoolid, sign_type, is_numing, sign_num, port, tid, imusername, impassword)))
            while int(time.time()) <= daterange[d][1]:
                if USER_LIST.get(uid):
                    await asyncio.sleep(1)
                else:
                    return
            if d != len(daterange)-1:
                for m in USER_LIST[uid]["main_sign_task"]:
                    if not m.done():
                        m.cancel()
                event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}定时签到模式所指定本次的监控停止时间已到，签到监控已停止，下次签到监控启动时间为{datetime.datetime.fromtimestamp(daterange[d+1][0]).strftime('%Y-%m-%d %H:%M:%S')}"}))
                await send_message(encrypt)
                LOGGER.info(f"{uid}-{name}:定时签到模式所指定本次的监控停止时间已到，下次签到监控启动时间为{datetime.datetime.fromtimestamp(daterange[d+1][0]).strftime('%Y-%m-%d %H:%M:%S')}")
        event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
        event_time2 = datetime.datetime.strftime(datetime.datetime.now(), "%Y-%m-%d %H:%M:%S")
        task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统停止监控通知]</p><p style=\"text-indent:2em\">[监控停止时间] {event_time2}</p><p style=\"text-indent:2em\">[监控停止原因] 定时签到模式所指定监控停止最晚时间已到</p><p style=\"text-indent:2em\">如需重新启动签到监控请登录学习通在线自动签到系统并重新启动签到监控。</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通在线自动签到系统停止监控通知"))
        BACKGROUND_TASKS.add(task)
        task.add_done_callback(BACKGROUND_TASKS.discard)
        await send_wechat_message(uid, "other", "学习通在线自动签到系统停止监控通知", {"监控停止时间": event_time2, "监控停止原因": "定时签到模式所指定监控停止最晚时间已到"}, "如需重新启动签到监控请登录学习通在线自动签到系统并重新启动签到监控", start_time=event_time2, reason="签到监控正常停止")
        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}定时签到模式所指定监控停止时间已到"}))
        await send_message(encrypt)
        LOGGER.info(f"{uid}-{name}:定时签到模式所指定监控停止时间已到")
        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "stop_sign", "uid": uid, "name": name}))
        await send_message(encrypt)
        await remove_sign_info(uid, name)
    except Exception:
        await record_error_log(traceback.format_exc(), False)


@retry(wait=wait_fixed(2))
async def get_joined_chatgroups(uid, name, imuid, token):
    r = await get_request(uid, name, USER_LIST[uid]["session"], f"https://a1-vip6.easemob.com/cx-dev/cxstudy/users/{imuid}/joined_chatgroups", {"detail": "true", "version": "v3", "pagenum": 1, "pagesize": 10000}, {"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 Edg/141.0.0.0"}, need_status_code=True)
    if r["status_code"] == 429:
        await record_error_log(f"{uid}-{name}:获取加入群聊列表失败，等待2秒后重试")
        raise ValueError
    elif r["status_code"] != 200:
        await record_debug_log(f"{uid}-{name}:获取加入群聊列表失败，准备执行签到监控异常停止事件", False)
        task = asyncio.create_task(stop_reason(2, uid, name, USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"]))
        BACKGROUND_TASKS.add(task)
        task.add_done_callback(BACKGROUND_TASKS.discard)
        return None
    return r


async def start_sign(uid, name, schoolid, sign_type, is_numing, sign_num, port, tid, imusername, impassword):
    try:
        USER_LIST[uid]["clazzdata"] = []
        res = await get_request(uid, name, USER_LIST[uid]["session"], "https://mooc1-api.chaoxing.com/mycourse/backclazzdata", {"view": "json", "rss": 1})
        not_append_list = []
        if res.get("result") is None:
            if res.get("error") == "invalid_verify":
                await record_debug_log(f"{uid}-{name}:课程列表获取失败，准备执行签到监控异常停止事件", False)
                task = asyncio.create_task(stop_reason(2, uid, name, USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"]))
                BACKGROUND_TASKS.add(task)
                task.add_done_callback(BACKGROUND_TASKS.discard)
                return
            else:
                await record_error_log(f"{uid}-{name}:{await json_encode(res)}", False)
                return
        if not res["result"]:
            await record_debug_log(f"{uid}-{name}:课程列表获取失败，准备执行签到监控异常停止事件", False)
            task = asyncio.create_task(stop_reason(2, uid, name, USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"]))
            BACKGROUND_TASKS.add(task)
            task.add_done_callback(BACKGROUND_TASKS.discard)
            return
        for d in res["channelList"]:
            if d["cataid"] == "100000002":
                if d["content"]["roletype"] == 3:
                    if d["content"]["state"] == 0:
                        pushdata = {"courseid": d["content"]["course"]["data"][0]["id"], "name": d["content"]["course"]["data"][0]["name"], "classid": d["content"]["id"], "sign_number": 0}
                        USER_LIST[uid]["clazzdata"].append(pushdata)
                    not_append_list.append([d["content"]["course"]["data"][0]["id"], d["content"]["id"]])
                else:
                    for c in d["content"]["clazz"]:
                        if [d["content"]["id"], c["clazzId"]] not in not_append_list:
                            not_append_list.append([d["content"]["id"], c["clazzId"]])
        res = await post_request(uid, name, USER_LIST[uid]["session"], "https://a1-vip6.easemob.com/cx-dev/cxstudy/token", {"grant_type": "password", "username": imusername, "password": impassword}, True)
        if res["status_code"] != 200:
            await record_debug_log(f"{uid}-{name}:登录IM失败，无法获取token，准备执行签到监控异常停止事件", False)
            task = asyncio.create_task(stop_reason(2, uid, name, USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"]))
            BACKGROUND_TASKS.add(task)
            task.add_done_callback(BACKGROUND_TASKS.discard)
            return
        token = res["access_token"]
        imuid = res["user"]["username"]
        r = await get_joined_chatgroups(uid, name, imuid, token)
        if not r:
            return
        cdata = r["data"]
        for item in cdata:
            if item["description"] != "" and item["description"] != "面对面群聊":
                class_data = await json_decode(item["description"])
                if (item["permission"] == "member" or item["permission"] == "admin") and class_data.get("groupType", 105) != 105 and class_data.get("courseInfo"):
                    if item["name"] == "":
                        course_name = class_data["courseInfo"]["coursename"]
                    else:
                        course_name = item["name"]
                    if class_data["courseInfo"].get("courseid "):
                        courseid = class_data["courseInfo"]["courseid "]
                    elif class_data["courseInfo"].get("courseid"):
                        courseid = class_data["courseInfo"]["courseid"]
                    else:
                        continue
                    if [courseid, class_data["courseInfo"]["classid"]] not in not_append_list:
                        pushdata = {"courseid": courseid, "name": course_name, "classid": class_data["courseInfo"]["classid"], "sign_number": 0}
                        USER_LIST[uid]["clazzdata"].append(pushdata)
                        not_append_list.append([courseid, class_data["courseInfo"]["classid"]])
        rt = 0
        monitor_port = ""
        if USER_LIST.get(uid):
            if 2 in port:
                monitor_port = "接口2（APP端接口）"
            elif 3 in port:
                monitor_port = "接口3（网页端接口）"
            elif 4 in USER_LIST[uid]["port"]:
                monitor_port = "接口4（主备用接口）"
        else:
            return
        event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}课程和班级列表获取成功，共获取到{len(USER_LIST[uid]['clazzdata'])}条课程和班级数据，签到监控已启动，当前监控接口为{monitor_port}"}))
        await send_message(encrypt)
        LOGGER.info(f"{uid}-{name}:课程和班级列表获取成功，共获取到{len(USER_LIST[uid]['clazzdata'])}条课程和班级数据，签到监控已启动，当前监控接口为{monitor_port}")
        is_night = False
        while True:
            for clazzdata in list(USER_LIST[uid]["clazzdata"]):
                if not NODE_CONFIG["night_monitor"]:
                    now = datetime.datetime.now().time()
                    while (now >= datetime.time(23)) or (now <= datetime.time(6)):
                        if not is_night:
                            await record_debug_log(f"{uid}-{name}:暂停使用{monitor_port}进行签到监控")
                            event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                            is_night = True
                            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}{monitor_port}每日23时至次日6时暂停签到监控"}))
                            await send_message(encrypt)
                        await asyncio.sleep(1)
                        now = datetime.datetime.now().time()
                    if is_night:
                        await record_debug_log(f"{uid}-{name}:继续使用{monitor_port}进行签到监控")
                        event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}{monitor_port}继续进行签到监控"}))
                        await send_message(encrypt)
                        is_night = False
                na = clazzdata["name"]
                if 2 in USER_LIST[uid]["port"]:
                    rt = await interface_two(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid)
                elif 3 in USER_LIST[uid]["port"]:
                    rt = await interface_three(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid)
                elif 4 in USER_LIST[uid]["port"]:
                    rt = await interface_four(uid, name, clazzdata, schoolid, sign_type, is_numing, sign_num, na, tid)
                if rt == 1:
                    await record_debug_log(f"{uid}-{name}:收到上层函数的1返回值，退出循环", False)
                    return
                elif rt == 2:
                    await record_debug_log(f"{uid}-{name}:收到上层函数的2返回值，将该课程从课程列表中删除", False)
                    USER_LIST[uid]["clazzdata"].remove(clazzdata)
                elif rt == 3:
                    await record_debug_log(f"{uid}-{name}:等待1小时")
                    await asyncio.sleep(3600)
            await record_debug_log(f"{uid}-{name}:等待300秒")
            await asyncio.sleep(300)
    except Exception:
        await record_error_log(traceback.format_exc(), False)


def init_db():
    """ 初始化数据库 """
    conn = sqlite3.connect(os.path.join(REALPATH, "main.db"))
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cookies (
            uid TEXT PRIMARY KEY,
            cookies TEXT
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()


async def set_cookies(uid: str, cookies: dict):
    """ cookies 储存到数据库 """
    LOGGER.debug(f"写入cookies: {uid} {dict(cookies)}")

    def __main():
        try:
            conn = sqlite3.connect(os.path.join(REALPATH, "main.db"))
            cursor = conn.cursor()
            sql = "REPLACE INTO cookies(uid, cookies) VALUES(?, ?)"
            cursor.execute(sql, (uid, orjson.dumps(cookies).decode()))
            conn.commit()
            cursor.close()
            conn.close()
            return None
        except Exception:
            LOGGER.error(traceback.format_exc())
            return None
    async with SQL_LOCK:
        return await asyncio.to_thread(__main)


async def get_cookies(uid: str) -> dict:
    """ 从数据库获取cookies """

    def __main():
        try:
            conn = sqlite3.connect(os.path.join(REALPATH, "main.db"))
            cursor = conn.cursor()
            cursor.execute("SELECT cookies FROM cookies WHERE uid=?", (uid,))
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            if row:
                return orjson.loads(row[0].encode())
            else:
                return {}
        except Exception:
            LOGGER.error(traceback.format_exc())
            return {}
    _res = await asyncio.to_thread(__main)
    LOGGER.debug(f"读取cookies: {uid} {_res}")
    return _res


async def delete_cookies(not_delete_uids: list[str]):
    """ 删除数据库cookies
    :param not_delete_uids: 不删除的uid的列表
    """
    def __main():
        LOGGER.debug(f"清理失效cookies {not_delete_uids}")
        try:
            conn = sqlite3.connect(os.path.join(REALPATH, "main.db"))
            cursor = conn.cursor()
            cursor.execute("SELECT uid FROM cookies")
            rows = cursor.fetchall()
            for row in rows:
                if row[0] not in not_delete_uids:
                    cursor.execute("DELETE FROM cookies WHERE uid=?", (row[0],))
            conn.commit()
            cursor.close()
            conn.close()
            return None
        except Exception:
            LOGGER.error(traceback.format_exc())
            return None
    async with SQL_LOCK:
        return await asyncio.to_thread(__main)


async def person_sign(uid, name, username, student_number, password, schoolid, cookie, port, sign_type, is_timing, is_numing, sign_num, daterange, set_address, address, longitude, latitude, set_objectid, objectid, bind_email, email, useragent, devicecode, lock):
    session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=SSL_CONTEXT))
    try:
        local_cookies = await get_cookies(uid)
        if password != "":
            status = await get_request(uid, name, session, "https://passport2.chaoxing.com/api/login", {"name": username, "pwd": password, "schoolid": "", "verify": 0})
            if status["result"]:
                status2 = await get_request(uid, name, session, "https://sso.chaoxing.com/apis/login/userLogin4Uname.do", {"ft": "true"})
                if status2["result"]:
                    if status2["msg"]["fid"] == 0:
                        fid = ""
                    else:
                        fid = str(status2["msg"]["fid"])
                    USER_LIST[uid] = {"port": port, "session": session, "name": status["realname"], "username": username, "password": password, "student_number": student_number, "schoolid": fid, "cookie": cookie, "sign_type": sign_type, "is_timing": is_timing, "is_numing": is_numing, "daterange": daterange, "sign_num": sign_num, "set_address": set_address, "address": address, "longitude": longitude, "latitude": latitude, "set_objectId": set_objectid, "objectId": objectid, "bind_email": bind_email, "email": email, "header": {"Accept-Encoding": "gzip, deflate", "Accept-Language": "zh-CN,zh;q=0.9", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9", "User-Agent": useragent}, "deviceCode": devicecode, "signed_in_list": [], "success_sign_num": 0, "sign_task_list": {}, "main_sign_task": [], "first_check": True, "uncheck_course": [], "error_num": 0}
                    USER_LIST[uid]["main_sign_task"].append(asyncio.create_task(check_monitor_time(uid, name, schoolid, sign_type, is_timing, is_numing, sign_num, daterange, lock, port, status2["msg"]["uid"], status2["msg"]["accountInfo"]["imAccount"]["username"], status2["msg"]["accountInfo"]["imAccount"]["password"])))
                    return True
                elif cookie:
                    status2 = await get_request(uid, name, session, "https://sso.chaoxing.com/apis/login/userLogin4Uname.do", {"ft": "true"}, cookie=cookie, need_cookie=True)
                    if status2["result"]:
                        if status2["msg"]["fid"] == 0:
                            fid = ""
                        else:
                            fid = str(status2["msg"]["fid"])
                        USER_LIST[uid] = {"port": port, "session": session, "name": status2["msg"]["name"], "username": username, "password": password, "student_number": student_number, "schoolid": fid, "cookie": status2["sign_cookie"], "sign_type": sign_type, "is_timing": is_timing, "is_numing": is_numing, "daterange": daterange, "sign_num": sign_num, "set_address": set_address, "address": address, "longitude": longitude, "latitude": latitude, "set_objectId": set_objectid, "objectId": objectid, "bind_email": bind_email, "email": email, "header": {"Accept-Encoding": "gzip, deflate", "Accept-Language": "zh-CN,zh;q=0.9", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9", "User-Agent": useragent}, "deviceCode": devicecode, "signed_in_list": [], "success_sign_num": 0, "sign_task_list": {}, "main_sign_task": [], "first_check": True, "uncheck_course": [], "error_num": 0}
                        task = asyncio.create_task(set_cookies(uid, status2["sign_cookie"]))
                        BACKGROUND_TASKS.add(task)
                        task.add_done_callback(BACKGROUND_TASKS.discard)
                        USER_LIST[uid]["main_sign_task"].append(asyncio.create_task(check_monitor_time(uid, name, schoolid, sign_type, is_timing, is_numing, sign_num, daterange, lock, port, status2["msg"]["uid"], status2["msg"]["accountInfo"]["imAccount"]["username"], status2["msg"]["accountInfo"]["imAccount"]["password"])))
                        return True
                    else:
                        await session.close()
                        return False
                else:
                    await session.close()
                    return False
            elif not cookie:
                status = await get_request(uid, name, session, "https://passport2.chaoxing.com/api/login", {"name": student_number, "pwd": password, "schoolid": schoolid, "verify": 0})
                if status["result"]:
                    status2 = await get_request(uid, name, session, "https://sso.chaoxing.com/apis/login/userLogin4Uname.do", {"ft": "true"})
                    if status2["result"]:
                        if status2["msg"]["fid"] == 0:
                            fid = ""
                        else:
                            fid = str(status2["msg"]["fid"])
                        USER_LIST[uid] = {"port": port, "session": session, "name": status["realname"], "username": username, "password": password, "student_number": student_number, "schoolid": fid, "cookie": cookie, "sign_type": sign_type, "is_timing": is_timing, "is_numing": is_numing, "daterange": daterange, "sign_num": sign_num, "set_address": set_address, "address": address, "longitude": longitude, "latitude": latitude, "set_objectId": set_objectid, "objectId": objectid, "bind_email": bind_email, "email": email, "header": {"Accept-Encoding": "gzip, deflate", "Accept-Language": "zh-CN,zh;q=0.9", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9", "User-Agent": useragent}, "deviceCode": devicecode, "signed_in_list": [], "success_sign_num": 0, "sign_task_list": {}, "main_sign_task": [], "first_check": True, "uncheck_course": [], "error_num": 0}
                        USER_LIST[uid]["main_sign_task"].append(asyncio.create_task(check_monitor_time(uid, name, schoolid, sign_type, is_timing, is_numing, sign_num, daterange, lock, port, status2["msg"]["uid"], status2["msg"]["accountInfo"]["imAccount"]["username"], status2["msg"]["accountInfo"]["imAccount"]["password"])))
                        return True
                    else:
                        await session.close()
                        return False
                else:
                    await session.close()
                    return False
            elif cookie:
                status2 = await get_request(uid, name, session, "https://sso.chaoxing.com/apis/login/userLogin4Uname.do", {"ft": "true"}, cookie=cookie, need_cookie=True)
                if status2["result"]:
                    if status2["msg"]["fid"] == 0:
                        fid = ""
                    else:
                        fid = str(status2["msg"]["fid"])
                    USER_LIST[uid] = {"port": port, "session": session, "name": status2["msg"]["name"], "username": username, "password": password, "student_number": student_number, "schoolid": fid, "cookie": status2["sign_cookie"], "sign_type": sign_type, "is_timing": is_timing, "is_numing": is_numing, "daterange": daterange, "sign_num": sign_num, "set_address": set_address, "address": address, "longitude": longitude, "latitude": latitude, "set_objectId": set_objectid, "objectId": objectid, "bind_email": bind_email, "email": email, "header": {"Accept-Encoding": "gzip, deflate", "Accept-Language": "zh-CN,zh;q=0.9", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9", "User-Agent": useragent}, "deviceCode": devicecode, "signed_in_list": [], "success_sign_num": 0, "sign_task_list": {}, "main_sign_task": [], "first_check": True, "uncheck_course": [], "error_num": 0}
                    task = asyncio.create_task(set_cookies(uid, status2["sign_cookie"]))
                    BACKGROUND_TASKS.add(task)
                    task.add_done_callback(BACKGROUND_TASKS.discard)
                    USER_LIST[uid]["main_sign_task"].append(asyncio.create_task(check_monitor_time(uid, name, schoolid, sign_type, is_timing, is_numing, sign_num, daterange, lock, port, status2["msg"]["uid"], status2["msg"]["accountInfo"]["imAccount"]["username"], status2["msg"]["accountInfo"]["imAccount"]["password"])))
                    return True
                else:
                    await session.close()
                    return False
            else:
                await session.close()
                return False
        else:
            if local_cookies:
                status2 = await get_request(uid, name, session, "https://sso.chaoxing.com/apis/login/userLogin4Uname.do", {"ft": "true"}, cookie=local_cookies, need_cookie=True)
                if status2["result"]:
                    if status2["msg"]["fid"] == 0:
                        fid = ""
                    else:
                        fid = str(status2["msg"]["fid"])
                    USER_LIST[uid] = {"port": port, "session": session, "name": status2["msg"]["name"], "username": username, "password": password, "student_number": student_number, "schoolid": fid, "cookie": status2["sign_cookie"], "sign_type": sign_type, "is_timing": is_timing, "is_numing": is_numing, "daterange": daterange, "sign_num": sign_num, "set_address": set_address, "address": address, "longitude": longitude, "latitude": latitude, "set_objectId": set_objectid, "objectId": objectid, "bind_email": bind_email, "email": email, "header": {"Accept-Encoding": "gzip, deflate", "Accept-Language": "zh-CN,zh;q=0.9", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9", "User-Agent": useragent}, "deviceCode": devicecode, "signed_in_list": [], "success_sign_num": 0, "sign_task_list": {}, "main_sign_task": [], "first_check": True, "uncheck_course": [], "error_num": 0}
                    task = asyncio.create_task(set_cookies(uid, status2["sign_cookie"]))
                    BACKGROUND_TASKS.add(task)
                    task.add_done_callback(BACKGROUND_TASKS.discard)
                    USER_LIST[uid]["main_sign_task"].append(asyncio.create_task(check_monitor_time(uid, name, schoolid, sign_type, is_timing, is_numing, sign_num, daterange, lock, port, status2["msg"]["uid"], status2["msg"]["accountInfo"]["imAccount"]["username"], status2["msg"]["accountInfo"]["imAccount"]["password"])))
                    return True
            status2 = await get_request(uid, name, session, "https://sso.chaoxing.com/apis/login/userLogin4Uname.do", {"ft": "true"}, cookie=cookie, need_cookie=True)
            if status2["result"]:
                if status2["msg"]["fid"] == 0:
                    fid = ""
                else:
                    fid = str(status2["msg"]["fid"])
                USER_LIST[uid] = {"port": port, "session": session, "name": status2["msg"]["name"], "username": username, "password": password, "student_number": student_number, "schoolid": fid, "cookie": status2["sign_cookie"], "sign_type": sign_type, "is_timing": is_timing, "is_numing": is_numing, "daterange": daterange, "sign_num": sign_num, "set_address": set_address, "address": address, "longitude": longitude, "latitude": latitude, "set_objectId": set_objectid, "objectId": objectid, "bind_email": bind_email, "email": email, "header": {"Accept-Encoding": "gzip, deflate", "Accept-Language": "zh-CN,zh;q=0.9", "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9", "User-Agent": useragent}, "deviceCode": devicecode, "signed_in_list": [], "success_sign_num": 0, "sign_task_list": {}, "main_sign_task": [], "first_check": True, "uncheck_course": [], "error_num": 0}
                task = asyncio.create_task(set_cookies(uid, status2["sign_cookie"]))
                BACKGROUND_TASKS.add(task)
                task.add_done_callback(BACKGROUND_TASKS.discard)
                USER_LIST[uid]["main_sign_task"].append(asyncio.create_task(check_monitor_time(uid, name, schoolid, sign_type, is_timing, is_numing, sign_num, daterange, lock, port, status2["msg"]["uid"], status2["msg"]["accountInfo"]["imAccount"]["username"], status2["msg"]["accountInfo"]["imAccount"]["password"])))
                return True
            else:
                await session.close()
                return False
    except Exception:
        await record_error_log(traceback.format_exc(), False)
        await session.close()
        return False


async def get_qrcode_for_ws(send_aid, qrcode_info, address, longitude, latitude, source, attend_list):
    for dk, dv in list(QRCODE_SIGN_DICT.items()):
        if not dv["sign_status"]:
            try:
                task = asyncio.create_task(check_qrcode(dk, send_aid, qrcode_info, address, longitude, latitude, source, USER_LIST[dv["uid"]]["session"], USER_LIST[dv["uid"]]["header"], USER_LIST[dv["uid"]]["deviceCode"]))
                BACKGROUND_TASKS.add(task)
                task.add_done_callback(BACKGROUND_TASKS.discard)
            except Exception:
                await record_error_log(traceback.format_exc(), False)
    for aid, data in list(attend_list.items()):
        classid = data["classid"]
        for uid in data["uid_list"]:
            if USER_LIST.get(uid) and QRCODE_SIGN_DICT.get(f"{uid}{aid}") is None and aid not in USER_LIST[uid]["signed_in_list"]:
                can_sign = True
                if USER_LIST[uid]["is_timing"]:
                    now = time.time()
                    can_sign = any(start <= now <= end for start, end in USER_LIST[uid]["daterange"])
                if can_sign:
                    try:
                        task = asyncio.create_task(check_qrcode_from_uncheck_sign(uid, USER_LIST[uid]["name"], classid, send_aid, qrcode_info, address, longitude, latitude, source, USER_LIST[uid]["session"], USER_LIST[uid]["header"], USER_LIST[uid]["sign_type"], USER_LIST[uid]["deviceCode"]))
                        BACKGROUND_TASKS.add(task)
                        task.add_done_callback(BACKGROUND_TASKS.discard)
                    except Exception:
                        await record_error_log(traceback.format_exc())


async def check_qrcode_from_uncheck_sign(uid, name, class_id, aid, qrcode_info, address, longitude, latitude, source, client, header, sign_type, devicecode):
    try:
        USER_LIST[uid]["signed_in_list"].append(aid)
        await record_debug_log(f"{uid}-{name}:收到签到二维码且用户暂未监控到该签到，准备直接签到")
        parsed_url = urlparse(qrcode_info)
        query_string = parsed_url.query
        params_dict_list_values = parse_qs(query_string, keep_blank_values=True)
        enc = params_dict_list_values["enc"][0]
        res2 = await get_request(uid, name, USER_LIST[uid]["session"], "https://mobilelearn.chaoxing.com/v2/apis/sign/getClassInfo", {"classId": class_id})
        await record_debug_log(f"{uid}-{name}:开始获取班级信息")
        if res2["result"] == 1:
            course_id = res2["data"]["courseId"]
            na = res2["data"]["courseName"]
            await record_debug_log(f"{uid}-{name}:成功获取班级信息")
        else:
            event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
            await record_debug_log(f"{uid}-{name}:未能成功获取班级信息，将取消签到，{await json_encode(res2)}", False)
            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}无法获取该签到所属班级信息，取消签到"}))
            await send_message(encrypt)
            LOGGER.info(f"{uid}-{name}:无法获取该签到所属班级信息，取消签到")
            return
        if await check_sign_type(uid, name, aid, sign_type):
            pptactiveinfo = await getpptactiveinfo(uid, name, aid)
            if pptactiveinfo is False:
                return
            name_one = pptactiveinfo["data"]["name"]
            event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}收到同班同学从{source}提交的签到二维码，并以此监测到课程或班级“{na}”的签到活动，签到活动名称为“{name_one}”"}))
            await send_message(encrypt)
            LOGGER.info(f"{uid}-{name}:收到同班同学从{source}提交的签到二维码，并以此监测到课程或班级“{na}”的签到活动，签到活动名称为“{name_one}”")
            aid_list = []
            if pptactiveinfo["data"].get("multiClassesActives"):
                await record_debug_log(f"{uid}-{name}:该签到设置了多班发放")
                for m in pptactiveinfo["data"]["multiClassesActives"]:
                    aid_list.append(str(m["aid"]))
            else:
                await record_debug_log(f"{uid}-{name}:该签到未设置多班发放")
                aid_list.append(aid)
            start_time = pptactiveinfo["data"]["starttimeStr"]
            start_timestamp = pptactiveinfo["data"]["starttime"]//1000
            if not pptactiveinfo["data"]["manual"]:
                await record_debug_log(f"{uid}-{name}:该签到未设置手动结束")
                end_time = wechat_end_time = pptactiveinfo["data"]["endtimeStr"]
                timelong = f"{pptactiveinfo['data']['day']}天{pptactiveinfo['data']['hour']}小时{pptactiveinfo['data']['minute']}分钟"
            else:
                await record_debug_log(f"{uid}-{name}:该签到为手动结束")
                end_time = "无"
                wechat_end_time = datetime.datetime.strftime(datetime.datetime.fromtimestamp(start_timestamp+86400), "%Y-%m-%d %H:%M:%S")
                timelong = "教师手动结束签到"
            if pptactiveinfo["data"].get("timer"):
                check_aid = str(pptactiveinfo["data"]["timer"]["timerSignId"])
            else:
                check_aid = aid
            signout_email_append_text = ""
            signout_wechat_append_text = {}
            if pptactiveinfo["data"]["activeType"] == 2:
                if pptactiveinfo["data"].get("openSignOutFlag"):
                    await record_debug_log(f"{uid}-{name}:该签到设置了下课签退")
                    signout_start_time = datetime.datetime.strftime(datetime.datetime.fromtimestamp(pptactiveinfo["data"]["signOutPublishTimeStamp"]/1000-5), "%Y-%m-%d %H:%M:%S")
                    signout_timelong = await get_timelong(pptactiveinfo["data"]["signOutDuration"])
                    activetype_append_text = "，且教师设置了下课签退"
                    signout_email_append_text = f"<p style=\"text-indent:2em\">[签退大致开始时间] {signout_start_time}</p><p style=\"text-indent:2em\">[签退持续时间] {signout_timelong}</p>"
                    signout_wechat_append_text = {"签退大致开始时间": signout_start_time, "签退持续时间": signout_timelong}
                else:
                    await record_debug_log(f"{uid}-{name}:该签到未设置下课签退")
                    activetype_append_text = "，且教师未设置下课签退"
            else:
                await record_debug_log(f"{uid}-{name}:该签到为下课签退")
                activetype_append_text = "，且该签到为下课签退"
            event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
            event_time2 = datetime.datetime.strftime(datetime.datetime.now(), "%Y-%m-%d %H:%M:%S")
            set_address = ""
            set_longitude = -1
            set_latitude = -1
            if pptactiveinfo["data"]["ifrefreshewm"] == 1 and pptactiveinfo["data"]["ifopenAddress"] == 1:
                await record_debug_log(f"{uid}-{name}:该签到二维码会刷新且指定了签到位置，开始获取签到指定位置信息")
                sign_location_info = await get_sign_location_info(uid, name, check_aid)
                address = sign_location_info["address"]
                if address is None:
                    await record_debug_log(f"{uid}-{name}:未能成功获取签到指定位置信息，原因为“{sign_location_info['msg']}”", False)
                    send_text1 = f"指定位置信息解析失败，失败原因为“{sign_location_info['msg']}”，等待同班同学使用微信小程序“WAADRI的工具箱”指定签到位置并扫描学习通签到二维码"
                    send_text2 = f"，但指定位置信息解析失败，失败原因为“{sign_location_info['msg']}”，请让同班同学使用微信小程序“WAADRI的工具箱”指定签到位置并扫描学习通签到二维码来完成自动签到"
                else:
                    await record_debug_log(f"{uid}-{name}:成功获取签到指定位置信息")
                    set_address = address
                    set_longitude = sign_location_info["longitude"]
                    set_latitude = sign_location_info["latitude"]
                    send_text1 = "等待同班同学使用微信小程序“WAADRI的工具箱”扫描学习通签到二维码"
                    send_text2 = "，请让同班同学使用微信小程序“WAADRI的工具箱”扫描学习通签到二维码来完成自动签到"
                sign_type = f"{pptactiveinfo['data']['ewmRefreshTime']}秒自动更新且指定了签到地点的二维码签到"
                await send_wechat_message(uid, "sign", "发现签到，等待扫码", f"{send_text1}来完成自动签到", icon="time", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"{pptactiveinfo['data']['ewmRefreshTime']}秒自动更新且指定了签到地点的二维码签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text, is_qrcode_sign=True)
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到为{pptactiveinfo['data']['ewmRefreshTime']}秒自动更新且指定了签到地点的二维码签到{activetype_append_text}{send_text2}，小程序使用教程见https://doc.waadri.top/guide/%E4%BA%8C%E7%BB%B4%E7%A0%81%E7%AD%BE%E5%88%B0.html"}))
                await send_message(encrypt)
                LOGGER.info(f"{uid}-{name}:监测到{pptactiveinfo['data']['ewmRefreshTime']}秒自动更新且指定了签到地点的二维码签到{activetype_append_text}")
            elif pptactiveinfo["data"]["ifrefreshewm"] == 1:
                await record_debug_log(f"{uid}-{name}:该签到二维码会刷新且没有指定签到位置")
                sign_type = f"{pptactiveinfo['data']['ewmRefreshTime']}秒自动更新且未指定签到地点的二维码签到"
                await send_wechat_message(uid, "sign", "发现签到，等待扫码", "等待同班同学使用微信小程序“WAADRI的工具箱”扫描学习通签到二维码来完成自动签到", icon="time", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"{pptactiveinfo['data']['ewmRefreshTime']}秒自动更新且未指定签到地点的二维码签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text, is_qrcode_sign=True)
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到为{pptactiveinfo['data']['ewmRefreshTime']}秒自动更新且未指定签到地点的二维码签到{activetype_append_text}，请让同班同学使用微信小程序“WAADRI的工具箱”扫描学习通签到二维码来完成自动签到，小程序使用教程见https://doc.waadri.top/guide/%E4%BA%8C%E7%BB%B4%E7%A0%81%E7%AD%BE%E5%88%B0.html"}))
                await send_message(encrypt)
                LOGGER.info(f"{uid}-{name}:监测到{pptactiveinfo['data']['ewmRefreshTime']}秒自动更新且未指定签到地点的二维码签到{activetype_append_text}")
            elif pptactiveinfo["data"]["ifopenAddress"] == 1:
                await record_debug_log(f"{uid}-{name}:该签到二维码不会刷新且指定了签到位置，开始获取签到指定位置信息")
                sign_location_info = await get_sign_location_info(uid, name, check_aid)
                address = sign_location_info["address"]
                if address is None:
                    await record_debug_log(f"{uid}-{name}:未能成功获取签到指定位置信息，原因为“{sign_location_info['msg']}”", False)
                    send_text1 = f"指定位置信息解析失败，失败原因为“{sign_location_info['msg']}”，等待同班同学使用微信小程序“WAADRI的工具箱”指定签到位置并扫描学习通签到二维码"
                    send_text2 = f"，但指定位置信息解析失败，失败原因为“{sign_location_info['msg']}”，请让同班同学使用微信小程序“WAADRI的工具箱”指定签到位置并扫描学习通签到二维码来完成自动签到"
                else:
                    await record_debug_log(f"{uid}-{name}:成功获取签到指定位置信息")
                    set_address = address
                    set_longitude = sign_location_info["longitude"]
                    set_latitude = sign_location_info["latitude"]
                    send_text1 = "等待同班同学使用微信小程序“WAADRI的工具箱”扫描学习通签到二维码"
                    send_text2 = "，请让同班同学使用微信小程序“WAADRI的工具箱”扫描学习通签到二维码来完成自动签到"
                sign_type = "无自动更新且指定了签到地点的二维码签到"
                await send_wechat_message(uid, "sign", "发现签到，等待扫码", f"{send_text1}来完成自动签到", icon="time", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"无自动更新且指定了签到地点的二维码签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text, is_qrcode_sign=True)
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到为无自动更新且指定了签到地点的二维码签到{activetype_append_text}{send_text2}，小程序使用教程见https://doc.waadri.top/guide/%E4%BA%8C%E7%BB%B4%E7%A0%81%E7%AD%BE%E5%88%B0.html"}))
                await send_message(encrypt)
                LOGGER.info(f"{uid}-{name}:监测到无自动更新且指定了签到地点的二维码签到{activetype_append_text}")
            else:
                await record_debug_log(f"{uid}-{name}:该签到二维码不会刷新且没有指定签到位置")
                sign_type = "无自动更新且未指定签到地点的二维码签到"
                await send_wechat_message(uid, "sign", "发现签到，等待扫码", "等待同班同学使用微信小程序“WAADRI的工具箱”扫描学习通签到二维码来完成自动签到", icon="time", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"无自动更新且未指定签到地点的二维码签到{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text, is_qrcode_sign=True)
                encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}该签到为无自动更新且未指定签到地点的二维码签到{activetype_append_text}，请让同班同学使用微信小程序“WAADRI的工具箱”扫描学习通签到二维码来完成自动签到，小程序使用教程见https://doc.waadri.top/guide/%E4%BA%8C%E7%BB%B4%E7%A0%81%E7%AD%BE%E5%88%B0.html"}))
                await send_message(encrypt)
                LOGGER.info(f"{uid}-{name}:监测到无自动更新且未指定签到地点的二维码签到{activetype_append_text}")
            temp_data = {"name": name, "courseid": course_id, "classid": class_id, "aid": aid, "aid_list": aid_list, "uid": uid, "lesson_name": na, "address": set_address, "longitude": set_longitude, "latitude": set_latitude, "event_time2": event_time2, "name_one": name_one, "sign_type": sign_type, "start_time": start_time, "end_time": end_time, "wechat_end_time": wechat_end_time, "timelong": timelong, "sign_status": False, "activetype_append_text": activetype_append_text, "signout_email_append_text": signout_email_append_text, "signout_wechat_append_text": signout_wechat_append_text, "start_timestamp": start_timestamp}
            QRCODE_SIGN_DICT[f"{uid}{aid}"] = temp_data
            await record_debug_log(f"{uid}-{name}:签到相关信息写入二维码签到字典队列中")
            encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "add_qrcode_sign", "aid_list": aid_list, "name": name}))
            await send_message(encrypt)
            if set_address != "" and str(set_longitude) != "" and str(set_longitude) != "-1" and str(set_latitude) != "" and str(set_latitude) != "-1":
                address = set_address
                longitude = set_longitude
                latitude = set_latitude
            location = await json_encode({"result": 1, "latitude": latitude, "longitude": longitude, "mockData": {"strategy": 0, "probability": 0}, "address": address})
            res = await get_request(uid, name, client, "https://mobilelearn.chaoxing.com/newsign/signDetail", {"activePrimaryId": aid, "type": 1}, header)
            if res["status"] == 1:
                await record_debug_log(f"{uid}-{name}:二维码签到未结束")
                if (res["startTime"]["time"]/1000+86400) < int(time.time()):
                    await record_debug_log(f"{uid}-{name}:二维码签到发布时间超过24小时，取消签到")
                    if not QRCODE_SIGN_DICT[f"{uid}{aid}"]["sign_status"]:
                        QRCODE_SIGN_DICT[f"{uid}{aid}"]["sign_status"] = True
                        task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统二维码签到取消通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[对应课程或班级] {na}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] {sign_type}{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {start_time}</p><p style=\"text-indent:2em\">[签到结束时间] {end_time}</p><p style=\"text-indent:2em\">[签到持续时间] {timelong}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[签到状态] 收到同班同学从{source}提交的签到二维码与指定位置信息，但签到发布时长超过24小时，系统将不再对当前二维码签到活动进行签到</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通二维码签到结果：签到取消"))
                        BACKGROUND_TASKS.add(task)
                        task.add_done_callback(BACKGROUND_TASKS.discard)
                        await send_wechat_message(uid, "sign", "签到取消", f"收到同班同学从{source}提交的签到二维码与指定位置信息，但签到发布时长超过24小时，系统将不再对当前二维码签到活动进行签到", icon="error-circle", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"{sign_type}{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text, is_qrcode_sign=True)
                        event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}收到同班同学从{source}提交的课程或班级“{na}”的签到二维码与指定位置信息，但该签到发布时长超过24小时，系统将不再对当前二维码签到活动进行签到"}))
                        await send_message(encrypt)
                        LOGGER.info(f"{uid}-{name}:收到同班同学从{source}提交的课程或班级“{na}”的签到二维码与指定位置信息，但该签到发布时长超过24小时，系统将不再对当前二维码签到活动进行签到")
                else:
                    await record_debug_log(f"{uid}-{name}:二维码签到发布时间未超过24小时，开始签到")
                    task = asyncio.create_task(qrcode_sign_handle(client, f"{uid}{aid}", name, USER_LIST[uid]["schoolid"], course_id, class_id, aid, uid, qrcode_info, enc, location, source, na, USER_LIST[uid]["is_numing"], USER_LIST[uid]["sign_num"], event_time2, name_one, sign_type, start_time, end_time, wechat_end_time, timelong, header, devicecode, activetype_append_text, signout_email_append_text, signout_wechat_append_text))
                    BACKGROUND_TASKS.add(task)
                    task.add_done_callback(BACKGROUND_TASKS.discard)
            else:
                await record_debug_log(f"{uid}-{name}:二维码签到已结束，取消签到")
                if not QRCODE_SIGN_DICT[f"{uid}{aid}"]["sign_status"]:
                    QRCODE_SIGN_DICT[f"{uid}{aid}"]["sign_status"] = True
                    task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统二维码签到取消通知]</p><p style=\"text-indent:2em\">[签到监测时间] {event_time2}</p><p style=\"text-indent:2em\">[对应课程或班级] {na}</p><p style=\"text-indent:2em\">[签到活动名称] {name_one}</p><p style=\"text-indent:2em\">[签到类型] {sign_type}{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {start_time}</p><p style=\"text-indent:2em\">[签到结束时间] {end_time}</p><p style=\"text-indent:2em\">[签到持续时间] {timelong}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[签到状态] 收到同班同学从{source}提交的签到二维码与指定位置信息，但签到已结束，系统将不再对当前二维码签到活动进行签到</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通二维码签到结果：签到取消"))
                    BACKGROUND_TASKS.add(task)
                    task.add_done_callback(BACKGROUND_TASKS.discard)
                    await send_wechat_message(uid, "sign", "签到取消", f"收到同班同学从{source}提交的签到二维码与指定位置信息，但签到已结束，系统将不再对当前二维码签到活动进行签到", icon="error-circle", aid=aid, coursename=na, activename=name_one, start_time=start_time, stop_time=wechat_end_time, sign_info={"签到监测时间": event_time2, "对应课程或班级": na, "签到活动名称": name_one, "签到类型": f"{sign_type}{activetype_append_text}", "签到开始时间": start_time, "签到结束时间": end_time, "签到持续时间": timelong} | signout_wechat_append_text, is_qrcode_sign=True)
                    event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}收到同班同学从{source}提交的课程或班级“{na}”的签到二维码与指定位置信息，但该签到已结束，系统将不再对当前二维码签到活动进行签到"}))
                    await send_message(encrypt)
                    LOGGER.info(f"{uid}-{name}:收到同班同学从{source}提交的课程或班级“{na}”的签到二维码与指定位置信息，但该签到已结束，系统将不再对当前二维码签到活动进行签到")
    except Exception:
        await record_error_log(traceback.format_exc(), False)


async def check_qrcode(d, aid, qrcode_info, address, longitude, latitude, source, session, header, devicecode):
    try:
        if aid in QRCODE_SIGN_DICT[d]["aid_list"]:
            uid = QRCODE_SIGN_DICT[d]["uid"]
            name = QRCODE_SIGN_DICT[d]["name"]
            if QRCODE_SIGN_DICT[d]["address"] != "" and str(QRCODE_SIGN_DICT[d]["longitude"]) != "" and str(QRCODE_SIGN_DICT[d]["longitude"]) != "-1" and str(QRCODE_SIGN_DICT[d]["latitude"]) != "" and str(QRCODE_SIGN_DICT[d]["latitude"]) != "-1":
                address = QRCODE_SIGN_DICT[d]["address"]
                longitude = QRCODE_SIGN_DICT[d]["longitude"]
                latitude = QRCODE_SIGN_DICT[d]["latitude"]
            lesson_name = QRCODE_SIGN_DICT[d]["lesson_name"]
            activetype_append_text = QRCODE_SIGN_DICT[d]["activetype_append_text"]
            signout_email_append_text = QRCODE_SIGN_DICT[d]["signout_email_append_text"]
            signout_wechat_append_text = QRCODE_SIGN_DICT[d]["signout_wechat_append_text"]
            await record_debug_log(f"{uid}-{name}:收到签到二维码，准备签到")
            parsed_url = urlparse(qrcode_info)
            query_string = parsed_url.query
            params_dict_list_values = parse_qs(query_string, keep_blank_values=True)
            enc = params_dict_list_values["enc"][0]
            location = await json_encode({"result": 1, "latitude": latitude, "longitude": longitude, "mockData": {"strategy": 0, "probability": 0}, "address": address})
            res = await get_request(uid, name, session, "https://mobilelearn.chaoxing.com/newsign/signDetail", {"activePrimaryId": aid, "type": 1}, header)
            if res["status"] == 1:
                await record_debug_log(f"{uid}-{name}:二维码签到未结束")
                if (res["startTime"]["time"]/1000+86400) < int(time.time()):
                    await record_debug_log(f"{uid}-{name}:收到二维码且二维码签到发布时间超过24小时，取消签到")
                    if not QRCODE_SIGN_DICT[d]["sign_status"]:
                        QRCODE_SIGN_DICT[d]["sign_status"] = True
                        task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统二维码签到取消通知]</p><p style=\"text-indent:2em\">[签到监测时间] {QRCODE_SIGN_DICT[d]['event_time2']}</p><p style=\"text-indent:2em\">[对应课程或班级] {lesson_name}</p><p style=\"text-indent:2em\">[签到活动名称] {QRCODE_SIGN_DICT[d]['name_one']}</p><p style=\"text-indent:2em\">[签到类型] {QRCODE_SIGN_DICT[d]['sign_type']}{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {QRCODE_SIGN_DICT[d]['start_time']}</p><p style=\"text-indent:2em\">[签到结束时间] {QRCODE_SIGN_DICT[d]['end_time']}</p><p style=\"text-indent:2em\">[签到持续时间] {QRCODE_SIGN_DICT[d]['timelong']}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[签到状态] 收到同班同学从{source}提交的签到二维码与指定位置信息，但签到发布时长超过24小时，系统将不再对当前二维码签到活动进行签到</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通二维码签到结果：签到取消"))
                        BACKGROUND_TASKS.add(task)
                        task.add_done_callback(BACKGROUND_TASKS.discard)
                        await send_wechat_message(uid, "sign", "签到取消", f"收到同班同学从{source}提交的签到二维码与指定位置信息，但签到发布时长超过24小时，系统将不再对当前二维码签到活动进行签到", icon="error-circle", aid=aid, coursename=lesson_name, activename=QRCODE_SIGN_DICT[d]["name_one"], start_time=QRCODE_SIGN_DICT[d]["start_time"], stop_time=QRCODE_SIGN_DICT[d]["wechat_end_time"], sign_info={"签到监测时间": QRCODE_SIGN_DICT[d]["event_time2"], "对应课程或班级": lesson_name, "签到活动名称": QRCODE_SIGN_DICT[d]["name_one"], "签到类型": f"{QRCODE_SIGN_DICT[d]['sign_type']}{activetype_append_text}", "签到开始时间": QRCODE_SIGN_DICT[d]["start_time"], "签到结束时间": QRCODE_SIGN_DICT[d]["end_time"], "签到持续时间": QRCODE_SIGN_DICT[d]["timelong"]} | signout_wechat_append_text, is_qrcode_sign=True)
                        event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}收到同班同学从{source}提交的课程或班级“{lesson_name}”的签到二维码与指定位置信息，但该签到发布时长超过24小时，系统将不再对当前二维码签到活动进行签到"}))
                        await send_message(encrypt)
                        LOGGER.info(f"{uid}-{name}:收到同班同学从{source}提交的课程或班级“{lesson_name}”的签到二维码与指定位置信息，但该签到发布时长超过24小时，系统将不再对当前二维码签到活动进行签到")
                else:
                    await record_debug_log(f"{uid}-{name}:二维码签到发布时间未超过24小时，开始签到")
                    task = asyncio.create_task(qrcode_sign_handle(session, d, name, USER_LIST[uid]["schoolid"], QRCODE_SIGN_DICT[d]["courseid"], QRCODE_SIGN_DICT[d]["classid"], aid, uid, qrcode_info, enc, location, source, lesson_name, USER_LIST[uid]["is_numing"], USER_LIST[uid]["sign_num"], QRCODE_SIGN_DICT[d]["event_time2"], QRCODE_SIGN_DICT[d]["name_one"], QRCODE_SIGN_DICT[d]["sign_type"], QRCODE_SIGN_DICT[d]["start_time"], QRCODE_SIGN_DICT[d]["end_time"], QRCODE_SIGN_DICT[d]["wechat_end_time"], QRCODE_SIGN_DICT[d]["timelong"], header, devicecode, activetype_append_text, signout_email_append_text, signout_wechat_append_text))
                    BACKGROUND_TASKS.add(task)
                    task.add_done_callback(BACKGROUND_TASKS.discard)
            else:
                await record_debug_log(f"{uid}-{name}:二维码签到已结束，取消签到")
                if not QRCODE_SIGN_DICT[d]["sign_status"]:
                    QRCODE_SIGN_DICT[d]["sign_status"] = True
                    task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统二维码签到取消通知]</p><p style=\"text-indent:2em\">[签到监测时间] {QRCODE_SIGN_DICT[d]['event_time2']}</p><p style=\"text-indent:2em\">[对应课程或班级] {lesson_name}</p><p style=\"text-indent:2em\">[签到活动名称] {QRCODE_SIGN_DICT[d]['name_one']}</p><p style=\"text-indent:2em\">[签到类型] {QRCODE_SIGN_DICT[d]['sign_type']}{activetype_append_text}</p><p style=\"text-indent:2em\">[签到开始时间] {QRCODE_SIGN_DICT[d]['start_time']}</p><p style=\"text-indent:2em\">[签到结束时间] {QRCODE_SIGN_DICT[d]['end_time']}</p><p style=\"text-indent:2em\">[签到持续时间] {QRCODE_SIGN_DICT[d]['timelong']}</p>{signout_email_append_text}<p style=\"text-indent:2em\">[签到状态] 收到同班同学从{source}提交的签到二维码与指定位置信息，但签到已结束，系统将不再对当前二维码签到活动进行签到</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通二维码签到结果：签到取消"))
                    BACKGROUND_TASKS.add(task)
                    task.add_done_callback(BACKGROUND_TASKS.discard)
                    await send_wechat_message(uid, "sign", "签到取消", f"收到同班同学从{source}提交的签到二维码与指定位置信息，但签到已结束，系统将不再对当前二维码签到活动进行签到", icon="error-circle", aid=aid, coursename=lesson_name, activename=QRCODE_SIGN_DICT[d]["name_one"], start_time=QRCODE_SIGN_DICT[d]["start_time"], stop_time=QRCODE_SIGN_DICT[d]["wechat_end_time"], sign_info={"签到监测时间": QRCODE_SIGN_DICT[d]["event_time2"], "对应课程或班级": lesson_name, "签到活动名称": QRCODE_SIGN_DICT[d]["name_one"], "签到类型": f"{QRCODE_SIGN_DICT[d]['sign_type']}{activetype_append_text}", "签到开始时间": QRCODE_SIGN_DICT[d]["start_time"], "签到结束时间": QRCODE_SIGN_DICT[d]["end_time"], "签到持续时间": QRCODE_SIGN_DICT[d]["timelong"]} | signout_wechat_append_text, is_qrcode_sign=True)
                    event_time = datetime.datetime.strftime(datetime.datetime.now(), "[%Y-%m-%d %H:%M:%S]")
                    encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_sign_message", "uid": uid, "name": name, "message": f"{event_time}收到同班同学从{source}提交的课程或班级“{lesson_name}”的签到二维码与指定位置信息，但该签到已结束，系统将不再对当前二维码签到活动进行签到"}))
                    await send_message(encrypt)
                    LOGGER.info(f"{uid}-{name}:收到同班同学从{source}提交的课程或班级“{lesson_name}”的签到二维码与指定位置信息，但该签到已结束，系统将不再对当前二维码签到活动进行签到")
    except Exception:
        await record_error_log(traceback.format_exc(), False)


def get_data_base64_decode(data):
    base64_decode_str = base64.b64decode(data)
    return base64_decode_str


async def user_relogin_loop():
    global UN_NOTICE_USER_LIST
    while True:
        now = datetime.datetime.now()
        if now.weekday() == 6 and now.hour == 12 and now.minute == 0:
            try:
                for uid in list(USER_LIST):
                    await user_relogin(uid)
            except Exception:
                await record_error_log(traceback.format_exc(), False)
        elif now.hour == offline_hour and now.minute == offline_minute:
            await sign_server_ws.close()
        elif now.hour == 6 and now.minute == 0:
            UN_NOTICE_USER_LIST = []
        await asyncio.sleep(60)


async def user_relogin(uid):
    try:
        if USER_LIST[uid]["password"] != "":
            status = await get_request(uid, USER_LIST[uid]["name"], USER_LIST[uid]["session"], "https://passport2.chaoxing.com/api/login", {"name": USER_LIST[uid]["username"], "pwd": USER_LIST[uid]["password"], "schoolid": "", "verify": 0})
            if status["result"]:
                await get_request(uid, USER_LIST[uid]["name"], USER_LIST[uid]["session"], "https://sso.chaoxing.com/apis/login/userLogin4Uname.do", {"ft": "true"})
            else:
                status = await get_request(uid, USER_LIST[uid]["name"], USER_LIST[uid]["session"], "https://passport2.chaoxing.com/api/login", {"name": USER_LIST[uid]["student_number"], "pwd": USER_LIST[uid]["password"], "schoolid": USER_LIST[uid]["schoolid"], "verify": 0})
                if status["result"]:
                    await get_request(uid, USER_LIST[uid]["name"], USER_LIST[uid]["session"], "https://sso.chaoxing.com/apis/login/userLogin4Uname.do", {"ft": "true"})
    except Exception:
        await record_error_log(traceback.format_exc(), False)


async def get_new_cookie_loop():
    while True:
        try:
            await asyncio.sleep(10800)
            for uid in list(USER_LIST):
                try:
                    if USER_LIST[uid]["cookie"]:
                        await get_new_cookie(uid)
                except KeyError:
                    continue
                except Exception:
                    await record_error_log(traceback.format_exc())
        except Exception:
            await record_error_log(traceback.format_exc(), False)


async def get_new_cookie(uid):
    status2 = await get_request(uid, USER_LIST[uid]["name"], USER_LIST[uid]["session"], "https://sso.chaoxing.com/apis/login/userLogin4Uname.do", {"ft": "true"}, need_cookie=True)
    if status2["result"]:
        USER_LIST[uid]["cookie"] = status2["sign_cookie"]
        task = asyncio.create_task(set_cookies(uid, USER_LIST[uid]["cookie"]))
        BACKGROUND_TASKS.add(task)
        task.add_done_callback(BACKGROUND_TASKS.discard)
    else:
        name = USER_LIST[uid]["name"]
        if uid not in UN_NOTICE_USER_LIST:
            UN_NOTICE_USER_LIST.append(uid)
            event_time2 = datetime.datetime.strftime(datetime.datetime.now(), "%Y-%m-%d %H:%M:%S")
            task = asyncio.create_task(send_email(uid, name, f"<p>[学习通在线自动签到系统cookie过期通知]</p><p style=\"text-indent:2em\">您的账号cookie在自动续期时失败，这意味着后续您的签到监控可能因登录过期而异常停止，建议您重新登录一次签到系统并重启签到监控来确保使用最新的cookie进行签到监控。注意：本提示并非意味着您的签到监控目前已停止，仅提醒您签到监控后续有异常停止的可能</p>", USER_LIST[uid]["bind_email"], USER_LIST[uid]["email"], "学习通在线自动签到系统cookie过期通知"))
            BACKGROUND_TASKS.add(task)
            task.add_done_callback(BACKGROUND_TASKS.discard)
            task = asyncio.create_task(send_wechat_message(uid, "other", "学习通在线自动签到系统cookie过期通知", {}, "您的账号cookie在自动续期时失败，这意味着后续您的签到监控可能因登录过期而异常停止，建议您重新登录一次签到系统并重启签到监控来确保使用最新的cookie进行签到监控。注意：本提示并非意味着您的签到监控目前已停止，仅提醒您签到监控后续有异常停止的可能", start_time=event_time2, reason="cookie过期"))
            BACKGROUND_TASKS.add(task)
            task.add_done_callback(BACKGROUND_TASKS.discard)
        await record_error_log(f"{USER_LIST[uid]['name']}:cookie更新失败")


async def send_message(message):
    while True:
        try:
            if sign_server_ws.state == State.OPEN:
                try:
                    while MSG_SEND_LOCK.locked():
                        await asyncio.sleep(1)
                    await sign_server_ws.send(message)
                    break
                except websockets.exceptions.ConnectionClosedError:
                    await asyncio.sleep(1)
                except Exception:
                    await record_error_log(traceback.format_exc())
                    await asyncio.sleep(1)
            else:
                await asyncio.sleep(1)
                continue
        except Exception:
            await record_error_log(traceback.format_exc(), False)


def in_docker():
    try:
        if os.path.exists("/.dockerenv"):
            return True
        with open("/proc/1/cgroup", "rt") as f:
            cgroup = f.read()
        return any(k in cgroup for k in ["docker", "kubepods", "containerd"])
    except Exception:
        return False


async def send_wechat_message(uid, message_type, title, message, footer="", icon="", aid="", coursename="", activename="", start_time="", stop_time="", reason="", force_send=False, sign_info=None, is_qrcode_sign=False, is_manual_sign=None, is_group_sign=False):
    try:
        if not force_send and NODE_STRAT_TIME+240 >= time.time():
            not_send = True
        else:
            not_send = False
        encrypt = await asyncio.to_thread(get_data_aes_encode, await json_encode({"type": "send_wechat", "uid": uid, "message_type": message_type, "aid": aid, "title": title, "message": message, "footer": footer, "icon": icon, "coursename": coursename, "activename": activename, "start_time": start_time, "stop_time": stop_time, "reason": reason, "sign_info": sign_info, "is_qrcode_sign": is_qrcode_sign, "is_manual_sign": is_manual_sign, "is_group_sign": is_group_sign, "not_send": not_send}))
        await send_message(encrypt)
    except Exception:
        await record_error_log(traceback.format_exc(), False)


async def main():
    APP["CX_SESSION"] = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=SSL_CONTEXT))
    APP["SIGN_ERROR_LOG"] = await aiofiles.open(os.path.join(REALPATH, "node_error_log.log"), "a", encoding="utf-8")
    APP["SIGN_DEBUG_LOG"] = await aiofiles.open(os.path.join(REALPATH, "node_debug_log.log"), "a", encoding="utf-8")
    task = asyncio.create_task(sign_server_ws_monitor())
    if sys.platform != 'win32':
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
        loop.add_signal_handler(signal.SIGINT, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        for d in list(USER_LIST):
            await remove_sign_info(d, USER_LIST[d]["name"])
    finally:
        await APP["SIGN_ERROR_LOG"].close()
        await APP["SIGN_DEBUG_LOG"].close()
        await APP["CX_SESSION"].close()


if __name__ == "__main__":
    config_path = os.path.join(REALPATH, "node_config.yaml")
    if not os.path.isfile(config_path):
        LOGGER.warning("未检测到节点配置文件，将会自动在当前路径下生成默认配置文件，请稍后自行修改配置文件后再次运行本程序")
        time.sleep(3)
        yam_data = f'''# 配置文件修改时注意在单引号内填写，不熟悉yaml文件格式的用户可在 https://www.json.cn/yaml-editor/ 中进行编辑并确认无误后粘贴回配置文件
# 邮件功能配置区
email:
  # 用来发送邮件的邮箱地址如XXX@qq.com，未填写则不发送邮件
  address: ''
  # 用来发送邮件的邮箱密码，某些邮箱可能需要填写授权码
  password: ''
  # 是否使用tls或ssl加密连接，默认true为使用加密连接，如不使用请填false，需注意大小写
  use_tls: true
  # 发送邮件服务器的host主机名，如QQ邮箱的发送邮件服务器主机名为smtp.qq.com
  host: ''
  # 发送邮件服务器端口号，请注意上方配置使用tls的状态，两种状态下的端口号一般不同
  port: 465
  # 发件人名称，可自行填写想让接收方看到的发件人名称，不填写则接收方看到的名称为发送人邮件地址
  user: ''
# 节点名称、密码和人数配置区
node:
  # 节点名称，不能和已接入在线自动签到系统的其它第三方节点名称重复
  name: ''
  # 节点密码，设置后用户需要在网站中输入正确的密码才能使用该节点，留空则为不设置密码，此时任何人均可使用该节点进行签到
  password: ''
  # 限制节点使用人数，0为不限制使用人数
  limit: 0
# 是否开启用户频繁信息显示，关闭后当用户使用接口2或接口3出现“请勿频繁操作”提示后将不会在控制台展示此类信息，默认true为显示，不显示请填false，需注意大小写
show_frequently: true
# 是否开启夜间签到监控，当关闭时接口2和接口3将在每日23时至次日6时暂停使用上述接口用户的签到监控，可尽量避免夜间频繁请求导致接口出现频繁提示，此配置不影响接口1在夜间进行监控，默认true为开启夜间监控，如不开启请填false，需注意大小写
night_monitor: true
# 是否启用debug模式，启用后日志输出更加详细，方便排查问题，建议使用时出现问题且命令行中未展示问题详细信息时再启用，默认false为不输出，要输出debug日志请填true，需注意大小写
debug: false
# 节点uuid，第一次启动程序时会随机生成，请勿更改，否则无法匹配已经使用该节点启动监控的用户信息
uuid: {uuid.uuid4()}'''
        with open(config_path, "w", encoding="utf-8") as file:
            file.write(yam_data)
        LOGGER.info(f"配置文件已生成，路径为{config_path}，请修改其中的配置后再次运行程序")
        time.sleep(3)
        input("按回车键退出……")
        sys.exit()
    try:
        with open(config_path, encoding="utf-8") as file:
            config = yaml.safe_load(file)
        NODE_CONFIG["email"].update(config["email"])
        NODE_CONFIG["node"]["name"] = config["node"]["name"]
        NODE_CONFIG["node"]["password"] = config["node"]["password"]
        NODE_CONFIG["node"]["limit"] = int(config["node"]["limit"])
        NODE_CONFIG["show_frequently"] = config["show_frequently"]
        NODE_CONFIG["night_monitor"] = config["night_monitor"]
        NODE_CONFIG["debug"] = config["debug"]
        NODE_CONFIG["uuid"] = config["uuid"]
    except Exception:
        LOGGER.warning("节点配置文件已损坏无法读取，请删除配置文件后重新运行程序生成新的配置文件")
        time.sleep(3)
        input("按回车键退出……")
        sys.exit()
    if NODE_CONFIG["node"]["name"] == "":
        LOGGER.warning("节点名称不能为空，请修改配置文件后重新运行程序")
        time.sleep(3)
        input("按回车键退出……")
        sys.exit()
    elif NODE_CONFIG["uuid"] == "":
        LOGGER.warning("节点uuid不能为空，请删除当前配置文件后重新运行程序生成新的配置文件")
        time.sleep(3)
        input("按回车键退出……")
        sys.exit()
    if NODE_CONFIG["debug"]:
        LOGGER.setLevel(logging.DEBUG)
    else:
        LOGGER.setLevel(logging.INFO)
    try:
        cx_res = requests.get("https://cx-api.waadri.top/get_other_node_version.json", timeout=10).json()
        latest_version = cx_res["latest_version"]
        if latest_version == str(NODE_VERSION):
            LOGGER.info(f"当前节点程序已为最新版本\n当前版本更新日志：\n{cx_res['new_version_log']}")
            cx_res = requests.get("https://cx-api.waadri.top/get_timestamp", timeout=10).json()
            client_timestamp = int(time.time())
            server_timestamp = cx_res["timestamp"]
            if abs(server_timestamp-client_timestamp) >= 10:
                LOGGER.warning("您的设备系统时间与服务器时间相差过大，节点可能无法正常工作，请更新系统时间后再次启动节点")
                time.sleep(3)
                input("按回车键退出……")
                sys.exit()
        else:
            LOGGER.warning(f"节点程序检测到新版本，更新内容如下\n{cx_res['new_version_log']}")
            LOGGER.warning("正在下载新版本并替换旧版本")
            if in_docker():
                cx_res = requests.get(cx_res["docker_download_url"])
            else:
                cx_res = requests.get(cx_res["py_download_url"])
            with open(__file__, "wb") as file:
                file.write(cx_res.content)
            LOGGER.warning("下载完成，正在重新启动程序……")
            time.sleep(3)
            with open(os.path.join(REALPATH, "node_error_log.log"), "w", encoding="utf-8") as file:
                file.close()
            with open(os.path.join(REALPATH, "node_debug_log.log"), "w", encoding="utf-8") as file:
                file.close()
            os.execl(sys.executable, sys.executable, os.path.abspath(__file__))
    except Exception:
        LOGGER.debug(traceback.format_exc())
        LOGGER.warning("网络连接异常，版本更新检查失败")
        time.sleep(3)
    current_version = sys.version_info
    version_str = f"{current_version.major}.{current_version.minor}.{current_version.micro}"
    if current_version < (3, 10):
        LOGGER.warning(f"节点程序需要在python 3.10或更高版本下运行，您当前python版本为{version_str}，请安装python 3.10及以上版本后再次运行")
        time.sleep(3)
        input("按回车键退出……")
        sys.exit()
    else:
        LOGGER.info(f"您当前python版本为{version_str}，可以正常运行节点程序")
    init_db()
    asyncio.run(main())
