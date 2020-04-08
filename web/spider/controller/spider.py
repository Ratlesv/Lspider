#!/usr/bin/env python
# encoding: utf-8
'''
@author: LoRexxar
@contact: lorexxar@gmail.com
@file: spider.py
@time: 2020/3/12 15:54
@desc:
'''

import time
import datetime
import traceback
from queue import Queue, Empty
from bs4 import BeautifulSoup

from utils.LReq import LReq
from utils.log import logger

from core.htmlparser import html_parser
from core.urlparser import url_parser
from core.threadingpool import ThreadPool
from core.rabbitmqhandler import RabbitmqHandler

from LSpider.settings import LIMIT_DEEP

from web.spider.models import UrlTable
from web.index.models import ScanTask


class SpiderCoreBackend:
    """
    spider 守护线程
    """
    def __init__(self):
        # 任务与线程分发
        self.target_list = Queue()
        self.threadpool = ThreadPool()

        tasklist = ScanTask.objects.filter(is_active=True)

        for task in tasklist:
            lastscantime = datetime.datetime.strptime(str(task.last_scan_time)[:19], "%Y-%m-%d %H:%M:%S")
            nowtime = datetime.datetime.now()

            if lastscantime:
                if (nowtime - lastscantime).days > 30:
                    # 1 mouth
                    target = task.target
                    target_type = task.target_type

                    self.target_list.put({'url': target, 'type': target_type, 'deep': 0})

                    # 重设扫描时间
                    task.last_scan_time = nowtime
                    task.save()

        # 获取线程池然后分发信息对象
        # 当有空闲线程时才继续
        for i in range(self.threadpool.get_free_num()):
            spidercore = SpiderCore(self.target_list)
            logger.debug("[Spider Core] New Thread {} for Spider Core.".format(i))

            self.threadpool.new(spidercore.scan)
            time.sleep(0.5)

        self.threadpool.wait_all_thread()


class SpiderCore:
    """
    spider core thread
    """

    def __init__(self, target_list=Queue()):

        # rabbitmq init
        self.rabbitmq_handler = RabbitmqHandler()

        # self.target = target
        self.target_list = target_list

        self.req = LReq()

    def scan(self):
        i = 0

        while not self.target_list.empty() or i < 30:

            try:
                # sleep
                time.sleep(self.req.get_timeout())

                target = self.target_list.get(False)
                content = False

                if target['type'] == 'link':
                    content = self.req.getRespByChrome(target['url'])

                if target['type'] == 'js':
                    content = self.req.getResp(target['url'])

                if not content:
                    continue

                result_list = html_parser(content)
                result_list = url_parser(target['url'], result_list, target['deep'])

                print(result_list)
                # 继续把链接加入列表
                for target in result_list:

                    if target['deep'] > LIMIT_DEEP:
                        continue

                    # save to rabbitmq
                    self.rabbitmq_handler.new_scan_target(str(target))

                    self.target_list.put(target)

            except KeyboardInterrupt:
                logger.error("[Scan] Stop Scaning.")
                self.req.close_driver()
                exit(0)

            except Empty:
                i += 1
                time.sleep(1)

            except:
                logger.warning('[Scan] something error, {}'.format(traceback.format_exc()))
                continue

        # after target list finish
        self.req.close_driver()


if __name__ == "__main__":

    scancore = SpiderCore()

    scancore.target_list.put({'url': 'https://lorexxar.cn', 'type': 'link', 'deep': 0})
    # scancore.target_list.put({'url': "https://cdn.jsdelivr.net/npm/jquery@3.3.1/dist/jquery.min.js", 'type': 'js', 'deep': 0})
    scancore.scan()