import logging
import json
import asyncio
import aiohttp

from collections import defaultdict
from functools import wraps
from typing import List, Dict

_LOGGER = logging.getLogger(__name__)

TOKEN_URL = "https://zt.bjgas.com/bjgas-server/oauth/token"
USER_ID_URL = "https://zt.bjgas.com/bjgas-server/i/api/getUserId/{token}"
GAS_LIST_URL = "https://zt.bjgas.com/bjgas-server/i/api/nsgetUserGasListEncrypt/{encrypted_user_id}"
USER_INFO_URL = "https://zt.bjgas.com/bjgas-server/i/api/intelligent/queryUserInfo"
WEEK_QRY_URL = "https://zt.bjgas.com/bjgas-server/i/api/intelligent/getWeekQry"
YEAR_QRY_URL = "https://zt.bjgas.com/bjgas-server/i/api/intelligent/getYearQry"
STEP_QRY_URL = "https://zt.bjgas.com/bjgas-server/r/api?sysName=CCB&apiName=CM-MOB-IF07"
MAX_PRICE_STEP = 5


class LoginFailed(Exception):
    pass


class AuthFailed(Exception):
    pass


class InvalidData(Exception):
    pass


class GASData:
    DEFAULT_HEADERS = {
        "Host": "zt.bjgas.com",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Accept-Language": "zh-cn, zh-Hans; q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 "
                        "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.7(0x1800072c) "
                        "NetType/WIFI Language/zh_CN",
        "Connection": "keep-alive",
    }

    def __init__(self, session: aiohttp.ClientSession, login: Dict[str, str]):
        self._session = session
        self._login = login
        self._token = None

    def get_token(self):
        if not self._token:
            raise AuthFailed(f'get token fail, cannot found access token')
        return self._token

    async def refresh_token(self):
        try:
            r = await self._session.post(TOKEN_URL, params=dict(
                client_id=self._login['client_id'],
                client_secret=self._login['client_secret'],
                grant_type='password',
                username=self._login['encrypted_username'],
                password=self._login['encrypted_password'],
            ), headers=self.DEFAULT_HEADERS, timeout=10)
            r.raise_for_status()
            body = await r.json()

            access_token = body.get('access_token')
            if not access_token:
                raise ValueError(f'get token fail, cannot found access token, body= {body}')
            
            self._token = access_token
        except Exception as e:
            raise LoginFailed(f'refresh token fail, {e}')

    def common_headers(self):
        return dict(**self.DEFAULT_HEADERS, Authorization=f"Bearer {self.get_token()}")

    @staticmethod
    def _with_login_retry(f):
        @wraps(f)
        async def _f(self, *args, **kwargs):
            try:
                return await f(self, *args, **kwargs)
            except AuthFailed as e:
                _LOGGER.info(f'auth failed, refresh token and retry, {e}')
                await self.refresh_token()
                return await f(self, *args, **kwargs)
            except aiohttp.ClientResponseError as e:
                if e.status != 401:
                    raise e

                _LOGGER.info(f'token expired, refresh token and retry, {e}')
                await self.refresh_token()
                return await f(self, *args, **kwargs)

        return _f

    @_with_login_retry
    async def get_gas_list(self):
        headers = self.common_headers()
        r = await self._session.get(USER_ID_URL.format(token=self.get_token()), headers=headers, timeout=10)
        r.raise_for_status()

        body = await r.json()
        if not body["success"]:
            raise InvalidData(f"async_get_gas_list get user ids error: {body}")

        user_codes = []
        for row in body['rows']:
            encrypted_user_id = row.get('userId')
            if not encrypted_user_id:
                continue

            lr = await self._session.get(GAS_LIST_URL.format(encrypted_user_id=encrypted_user_id), headers=headers, timeout=10)
            lr.raise_for_status()

            list_body = await lr.json()
            if not list_body["success"]:
                raise InvalidData(f"async_get_gas_list get gas list error: row= {row} body= {body}")
            
            for gas in list_body['rows']:
                user_code = gas.get('userCode')
                if not user_code:
                    continue

                user_codes.append(user_code)

        return user_codes

    @_with_login_retry
    async def get_userinfo(self, user_code):
        headers = self.common_headers()
        r = await self._session.get(USER_INFO_URL, params=dict(userCode=user_code), headers=headers, timeout=10)
        r.raise_for_status()

        body = await r.json()
        if not body["success"]:
            raise InvalidData(f"async_get_userinfo error: {body}")

        data = body["rows"][0]
        return {
            "last_update": data["fiscalDate"],
            "balance": float(data["remainAmt"]),
            "battery_voltage": float(data["batteryVoltage"]),
            "current_price": float(data["gasPrice"]),
            "month_reg_qty": float(data["regQty"]),
            "mtr_status": data["mtrStatus"],
        }

    @_with_login_retry
    async def get_week(self, user_code):
        headers = self.common_headers()
        r = await self._session.get(WEEK_QRY_URL, params=dict(userCode=user_code), headers=headers, timeout=10)
        r.raise_for_status()

        body = await r.json()
        if not body["success"]:
            raise InvalidData(f"async_get_week error: {body}")

        data = body["rows"][0]["infoList"]
        return {
            "daily_bills": data,
        }

    @_with_login_retry
    async def get_year(self, user_code):
        headers = self.common_headers()
        r = await self._session.get(YEAR_QRY_URL, params=dict(userCode=user_code), headers=headers, timeout=10)
        r.raise_for_status()

        body = await r.json()
        if not body["success"]:
            raise InvalidData(f"async_get_year error: {body}")

        data = body["rows"][0]["infoList"]
        return {
            "monthly_bills": data,
        }

    @_with_login_retry
    async def get_step(self, user_code):
        headers = self.common_headers()
        headers["Content-Type"] = "application/json;charset=UTF-8"
        headers["Origin"] = "file://"

        r = await self._session.post(STEP_QRY_URL, headers=headers, json={"CM-MOB-IF07": {"input": {"UniUserCode": f"{user_code}"}}}, timeout=10)
        r.raise_for_status()
        body = await r.json()

        data = body["soapenv:Envelope"]["soapenv:Body"]["CM-MOB-IF07"]["output"]
        result = {"year_consume": float(data["TotalSq"])}
        for i in range(1, MAX_PRICE_STEP+1):
            leftover = data.get(f'Step{i}LeftoverQty', None)
            if leftover is None:
                result['current_level'] = i
                break

            fleftover = float(leftover)
            if fleftover <= 0:
                continue

            result['current_level'] = i
            result['current_level_remain'] = fleftover
            break

        return result

    @staticmethod
    async def _set_result(results, user_code, f):
        results[user_code].update(await f(user_code))

    async def async_get_data(self):
        results = defaultdict(dict)

        user_codes = await self.get_gas_list()
        tasks = []
        for user_code in user_codes:
            tasks.extend([
                self._set_result(results, user_code, self.get_userinfo),
                self._set_result(results, user_code, self.get_week),
                self._set_result(results, user_code, self.get_year),
                self._set_result(results, user_code, self.get_step),
            ])

        await asyncio.gather(*tasks)
        _LOGGER.debug(f"gas get data success, results= {results}")
        return results
