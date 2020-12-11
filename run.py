from telnetlib import Telnet
import time
from multiprocessing import Process, Manager
from ctypes import c_char_p
import os
import json
import re
import sys

ENCODING = 'gbk'

def syslog(x):
    print('[sys] %s' % x)

class Game:
    def __init__(self, client):
        self.client = client
        self.triggers = {}
        self.states = {}
        self.last = None

    def handle_cmd(self, cmd):
        pieces = cmd.split()
        if pieces[0] == '@load' and len(pieces) > 1:
            for i in range(1, len(pieces)):
                self.load_trigger(pieces[i])
        elif pieces[0] == '@unload' and len(pieces) > 1:
            for i in range(1, len(pieces)):
                self.unload_trigger(pieces[i])
        elif pieces[0] == '@unloadall':
            self.triggers.clear()
            syslog('Unloaded all triggers')
        elif pieces[0] == '@list':
            syslog('List triggers:')
            print(self.triggers)
        elif pieces[0] == '@states':
            syslog('Show states:')
            print(self.states)
        else:
            self.trigger_cmd(pieces)

    def check_triggers(self, x):
        for a, trigger in self.triggers.items():
            for b, item in enumerate(trigger):
                if self.is_triggered('%s@@%d' % (a, b), item, x):
                    vs = {}
                    if 'match' in item:
                        p = re.compile(item['match'])
                        m = p.search(x)
                        for i, v in enumerate(m.groups()):
                            vs['$%d' % (i+1)] = v
                    if 'out' in item:
                        out = item['out'].format(**self.states)
                        if out == '$$':
                            self.write(self.last)
                        else:
                            for k, v in vs.items():
                                out = out.replace(k, v)
                            self.write(out)
                    if 'set' in item:
                        for d in item['set']:
                            if isinstance(d['value'], str) and d['value'][0] == '$':
                                self.states[d['name']] = vs.get(d['value'])
                            else:
                                self.states[d['name']] = d['value']

    def is_triggered(self, key, item, x):
        if 'cmd' in item:
            return False
        if 'and' in item:
            for cond in item['and']:
                if not self.check_cond(cond):
                    return False
        if 'or' in item:
            tmp = False
            for cond in item['and']:
                if self.check_cond(cond):
                    tmp = True
                    break
            if not tmp:
                return False
        if 'match' in item:
            p = re.compile(item['match'])
            m = p.search(x)
            if m is None:
                return False
        if 'cd' in item:
            k = key + '@@cd'
            if k not in self.states:
                self.states[k] = 0
            last = self.states[k]
            if time.time() * 1000 - last < item['cd']:
                return False
        self.states[key + '@@cd'] = time.time() * 1000
        return True

    def check_cond(self, cond):
        cur = self.states.get(cond['name'])
        exp = cond['value']
        if cond['op'] == 'eq':
            return cur == exp
        elif cond['op'] == 'gt':
            return cur > exp
        elif cond['op'] == 'lt':
            return cur < exp
        else:
            return False

    def trigger_cmd(self, pieces):
        cmd = pieces[0][1:]
        for a, trigger in self.triggers.items():
            for b, item in enumerate(trigger):
                if 'cmd' in item and item['cmd'] == cmd:
                    if 'out' in item:
                        self.write(item['out'])
                    if 'set' in item:
                        for d in item['set']:
                            self.states[d['name']] = d['value']

    def load_trigger(self, trigger):
        path = 'triggers/%s.json' % trigger
        if not os.path.exists(path):
            syslog('Cannot find trigger [%s]' % trigger)
        else:
            try:
                f = open(path, 'r')
                self.triggers[trigger] = json.loads(f.read())
                f.close()
                syslog('Loaded trigger [%s]' % trigger)
            except Exception as e:
                syslog('Failed to load trigger [%s]: %s' % (trigger, str(e)))

    def unload_trigger(self, trigger):
        if trigger in self.triggers:
            self.triggers.pop(trigger)
            syslog('Unloaded trigger [%s]' % trigger)

    def write(self, msg):
        self.last = msg
        syslog("[trigger] %s" % msg)
        cmds = msg.split(';')
        msg = '\r\n'.join(cmds)
        self.client.write(bytes(msg, encoding=ENCODING) + b'\r\n')

def console(input_line):
    with Telnet('pkuxkx.net', 8080) as tn:
        game = Game(tn)
        for arg in sys.argv[1:]:
            game.load_trigger(arg)
        while True:
            try:
                x = tn.read_until(b'\n', 1)
                x = x.decode(ENCODING).rstrip('\r\n')
                if len(x) > 0:
                    print(x)
                game.check_triggers(x)
                if len(input_line.value) > 0:
                    if input_line.value[0] == ord('@'):
                        game.handle_cmd(input_line.value.decode(ENCODING))
                    else:
                        syslog("[input] %s" % input_line.value)
                        tn.write(input_line.value + b'\r\n')
                    input_line.value = b''
            except Exception as e:
                syslog("Caught exception: %s" % str(e))

if __name__ == '__main__':
    with Manager() as manager:
        input_line = manager.Value(c_char_p, b'')

        p = Process(target=console, args=(input_line,))
        p.start()
        while True:
            cmd = input()
            if cmd == '@exit':
                syslog('exit ...')
                exit()
            else:
                input_line.value = bytes(cmd, encoding=ENCODING)
