#!/usr/bin/env python

################### check_mssql_database.py ############################
# Version    : 2.0.2
# Date       : 06/09/2016
# Maintainer : Nagios Enterprises, LLC
# Licence    : GPLv3 (http://www.fsf.org/licenses/gpl.txt)
#
# Author/Maintainers:
#   Nicholas Scott (Original author, Nagios)
#   Jake Omann (Nagios)
#   Scott Wilkerson (Nagios)
#
# Changelog:
#   2.0.2 - Add ability Query multiple database in one query  --liulei
#   2.0.1 - Fixed bug where temp file was named same as other for host and numbers were coming back bogus. (NS)
#   2.0.0 - Complete Revamp/Rewrite based on the server version of this plugin (NS)
#   1.3.0 - Added ability specify MSSQL instances (NS)
#   1.2.0 - Added ability to monitor instances (NS)
#           Added check to see if pymssql is installed (NS)
#   1.1.0 - Fixed port bug allowing for non default ports (CBTSDon)
#           Added mode error checking which caused non-graceful exit (Thanks mike from austria)
#
########################################################################

import pymssql
import time
import sys
import tempfile
try:
    import cPickle as pickle
except:
    import pickle
from optparse import OptionParser, OptionGroup

BASE_QUERY = "SELECT cntr_value FROM sysperfinfo WHERE counter_name='%s' AND instance_name='%%s';"
DIVI_QUERY = "SELECT cntr_value FROM sysperfinfo WHERE counter_name LIKE '%s%%%%' AND instance_name='%%s';"

MODES = {
    
    'logcachehit'       : { 'help'      : 'Log Cache Hit Ratio',
                            'stdout'    : 'Database %s Log Cache Hit Ratio is %s%%',
                            'label'     : 'log_cache_hit_ratio',
                            'unit'      : '%',
                            'query'     : DIVI_QUERY % 'Log Cache Hit Ratio',
                            'type'      : 'divide',
                            'modifier'  : 100,
                            },
    
    'activetrans'       : { 'help'      : 'Active Transactions',
                            'stdout'    : 'Database %s Active Transactions is %s',
                            'label'     : 'log_file_usage',
                            'unit'      : '',
                            'query'     : BASE_QUERY % 'Active Transactions',
                            'type'      : 'standard',
                            },
    
    'logflushes'         : { 'help'      : 'Log Flushes Per Second',
                            'stdout'    : 'Database %s Log Flushes Per Second is %s/sec',
                            'label'     : 'log_flushes_per_sec',
                            'query'     : BASE_QUERY % 'Log Flushes/sec',
                            'type'      : 'delta'
                            },
    
    'logfileusage'      : { 'help'      : 'Log File Usage',
                            'stdout'    : 'Database %s Log File Usage is %s%%',
                            'label'     : 'log_file_usage',
                            'unit'      : '%',
                            'query'     : BASE_QUERY % 'Percent Log Used',
                            'type'      : 'standard',
                            },
    
    'transpec'          : { 'help'      : 'Transactions Per Second',
                            'stdout'    : 'Database %s Transactions Per Second is %s/sec',
                            'label'     : 'transactions_per_sec',
                            'query'     : BASE_QUERY % 'Transactions/sec',
                            'type'      : 'delta'
                            },
    
    'loggrowths'        : { 'help'      : 'Log Growths',
                            'stdout'    : 'Database %s Log Growths is %s',
                            'label'     : 'log_growths',
                            'query'     : BASE_QUERY % 'Log Growths',
                            'type'      : 'standard'
                            },
    
    'logshrinks'        : { 'help'      : 'Log Shrinks',
                            'stdout'    : 'Database %s Log Shrinks is %s',
                            'label'     : 'log_shrinks',
                            'query'     : BASE_QUERY % 'Log Shrinks',
                            'type'      : 'standard'
                            },
    
    'logtruncs'         : { 'help'      : 'Log Truncations',
                            'stdout'    : 'Database %s Log Truncations is %s',
                            'label'     : 'log_truncations',
                            'query'     : BASE_QUERY % 'Log Truncations',
                            'type'      : 'standard'
                            },
    
    'logwait'           : { 'help'      : 'Log Flush Wait Time',
                            'stdout'    : 'Database %s Log Flush Wait Time is %sms',
                            'label'     : 'log_wait_time',
                            'unit'      : 'ms',
                            'query'     : BASE_QUERY % 'Log Flush Wait Time',
                            'type'      : 'standard'
                            },
    
    'datasize'          : { 'help'      : 'Database Size',
                            'stdout'    : 'Database %s Database size is %sKB',
                            'label'     : 'KB',
                            'query'     : BASE_QUERY % 'Data File(s) Size (KB)',
                            'type'      : 'standard'
                            },
    
    'time2connect'      : { 'help'      : 'Time to connect to the database.' },
    
    'test'              : { 'help'      : 'Run tests of all queries against the database.' },
}

def return_nagios(ret):
    code = 0
    prefix = ''
    status = ''
    perfdata = ''
    
    for res in ret:
        options = res['options']
        result = res['result']
        strresult = str(res['result'])
        stdout = res['stdout']
        label = res['label']
        unit = res['unit']
        database = res['database']
        
        if int(options.critical) < int(options.warning):
            invert = True
        else:
            invert = False
        if is_within_range(options.critical, result, invert):
            if code < 2:
                prefix = 'CRITICAL: '
                code = 2
        elif is_within_range(options.warning, result, invert):
            if code < 1:
                prefix = 'WARNING: '
                code = 1
        else:
            if code == 0:
                prefix = 'OK: '

        strresult = str(result)
        stdout = stdout % (database, strresult)
        status = status + ' ' + stdout
        perfdata = perfdata + '%s_%s=%s%s;%s;%s;; ' % (database, label, strresult, unit, options.warning or '', options.critical or '')

    status = '%s%s' % (prefix, status)
    status = '%s|%s' % (status, perfdata)
    raise NagiosReturn(status, code)

class NagiosReturn(Exception):
    
    def __init__(self, message, code):
        self.message = message
        self.code = code

class MSSQLQuery(object):
    
    def __init__(self, query, options, database, label='', unit='', stdout='', host='', modifier=1, *args, **kwargs):
        self.query = query % database
        self.label = label
        self.unit = unit
        self.stdout = stdout
        self.options = options
        self.host = host
        self.modifier = modifier
        self.database = database
    
    def run_on_connection(self, connection):
        cur = connection.cursor()
        cur.execute(self.query)
        self.query_result = cur.fetchone()[0]
    
    def finish(self):
        ret = {"stdout": self.stdout, "result": self.result, "unit": self.unit, "label": self.label, "options": self.options, "database": self.database}
        return ret
    
    def calculate_result(self):
        self.result = float(self.query_result) * self.modifier
    
    def do(self, connection):
        self.run_on_connection(connection)
        self.calculate_result()
        return self.finish()

class MSSQLDivideQuery(MSSQLQuery):
    
    def calculate_result(self):
        self.result = (float(self.query_result[0]) / self.query_result[1]) * self.modifier
    
    def run_on_connection(self, connection):
        cur = connection.cursor()
        cur.execute(self.query)
        self.query_result = [x[0] for x in cur.fetchall()]

class MSSQLDeltaQuery(MSSQLQuery):
    
    def make_pickle_name(self):
        tmpdir = tempfile.gettempdir()
        tmpname = hash(self.host + self.database + self.query)
        self.picklename = '%s/mssql-%s.tmp' % (tmpdir, tmpname)
    
    def calculate_result(self):
        self.make_pickle_name()
        
        try:
            tmpfile = open(self.picklename)
        except IOError:
            tmpfile = open(self.picklename, 'w')
            tmpfile.close()
            tmpfile = open(self.picklename)
        try:
            try:
                last_run = pickle.load(tmpfile)
            except EOFError, ValueError:
                last_run = { 'time' : None, 'value' : None }
        finally:
            tmpfile.close()
        
        if last_run['time']:
            old_time = last_run['time']
            new_time = time.time()
            old_val  = last_run['query_result']
            new_val  = self.query_result
            self.result = ((new_val - old_val) / (new_time - old_time)) * self.modifier
        else:
            self.result = None
        
        new_run = { 'time' : time.time(), 'query_result' : self.query_result }
        
        #~ Will throw IOError, leaving it to aquiesce
        tmpfile = open(self.picklename, 'w')
        pickle.dump(new_run, tmpfile)
        tmpfile.close()

def is_within_range(nagstring, value, invert = False):
    if not nagstring:
        return False
    import re
    import operator
    first_float = r'(?P<first>(-?[0-9]+(\.[0-9]+)?))'
    second_float= r'(?P<second>(-?[0-9]+(\.[0-9]+)?))'
    actions = [ (r'^%s$' % first_float,lambda y: (value > float(y.group('first'))) or (value < 0)),
                (r'^%s:$' % first_float,lambda y: value < float(y.group('first'))),
                (r'^~:%s$' % first_float,lambda y: value > float(y.group('first'))),
                (r'^%s:%s$' % (first_float,second_float), lambda y: (value < float(y.group('first'))) or (value > float(y.group('second')))),
                (r'^@%s:%s$' % (first_float,second_float), lambda y: not((value < float(y.group('first'))) or (value > float(y.group('second')))))]
    for regstr,func in actions:
        res = re.match(regstr,nagstring)
        if res: 
            if invert:
                return not func(res)
            else:
                return func(res)
    raise Exception('Improper warning/critical format.')

def parse_args():
    usage = "usage: %prog -H hostname -U user -P password -D databases --mode"
    parser = OptionParser(usage=usage)
    
    required = OptionGroup(parser, "Required Options")
    required.add_option('-H', '--hostname', help='Specify MSSQL Server Address', default=None)
    required.add_option('-U', '--user', help='Specify MSSQL User Name', default=None)
    required.add_option('-P', '--password', help='Specify MSSQL Password', default=None)
    required.add_option('-D', '--databases', help='Specify the databases to check', default=None) 
    parser.add_option_group(required)
    
    connection = OptionGroup(parser, "Optional Connection Information")
    connection.add_option('-I', '--instance', help='Specify instance', default=None)
    connection.add_option('-p', '--port', help='Specify port.', default=None)
    parser.add_option_group(connection)
    
    nagios = OptionGroup(parser, "Nagios Plugin Information")
    nagios.add_option('-w', '--warning', help='Specify warning range.', default=None)
    nagios.add_option('-c', '--critical', help='Specify critical range.', default=None)
    parser.add_option_group(nagios)
    
    mode = OptionGroup(parser, "Mode Options")
    global MODES
    for k, v in zip(MODES.keys(), MODES.values()):
        mode.add_option('--%s' % k, action="store_true", help=v.get('help'), default=False)
    parser.add_option_group(mode)
    options, _ = parser.parse_args()
    
    if not options.hostname:
        parser.error('Hostname is a required option.')
    if not options.user:
        parser.error('User is a required option.')
    if not options.password:
        parser.error('Password is a required option.')
    if not options.databases:
        parser.error('Databases is a required option.')
    
    if options.instance and options.port:
        parser.error('Cannot specify both instance and port.')
    
    options.mode = None
    for arg in mode.option_list:
        if getattr(options, arg.dest) and options.mode:
            parser.error("Must choose one and only Mode Option.")
        elif getattr(options, arg.dest):
            options.mode = arg.dest
    
    return options

def connect_db(options):
    host = options.hostname
    if options.instance:
        host += "\\" + options.instance
    elif options.port:
        host += ":" + options.port
    start = time.time()
    mssql = pymssql.connect(host = host, user = options.user, password = options.password, database='master')
    total = time.time() - start
    return mssql, total, host

def main():
    options = parse_args()
    
    dbs = options.databases.split(",")
    ret = []
    mssql, total, host = connect_db(options)

    if options.mode =='test':
        run_tests(mssql, options, host, db)
        
    elif not options.mode or options.mode == 'time2connect':
        data = {"stdout": 'Database %s Time to connect was %ss', "result": total, "unit": 's', "label": 'time', "options": options, "database": "_Total"}
        ret.append(data)
    else:
        for db in dbs:
            ret.append(execute_query(mssql, options, db, host))
    
    return_nagios(ret)

def execute_query(mssql, options, db, host=''):
    sql_query = MODES[options.mode]
    sql_query['options'] = options
    sql_query['host'] = host
    sql_query['database'] = db
    query_type = sql_query.get('type')
    if query_type == 'delta':
        mssql_query = MSSQLDeltaQuery(**sql_query)
    elif query_type == 'divide':
        mssql_query = MSSQLDivideQuery(**sql_query)
    else:
        mssql_query = MSSQLQuery(**sql_query)
    return mssql_query.do(mssql)

def run_tests(mssql, options, host, db):
    failed = 0
    total  = 0
    del MODES['time2connect']
    del MODES['test']
    for mode in MODES.keys():
        total += 1
        options.mode = mode
        try:
            execute_query(mssql, options, host, db)
        except NagiosReturn:
            print "%s passed!" % mode
        except Exception, e:
            failed += 1
            print "%s failed with: %s" % (mode, e)
    print '%d/%d tests failed.' % (failed, total)
    
if __name__ == '__main__':
    try:
        main()
    except pymssql.OperationalError, e:
        print e
        sys.exit(3)
    except IOError, e:
        print e
        sys.exit(3)
    except NagiosReturn, e:
        print e.message
        sys.exit(e.code)


