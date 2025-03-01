#!/usr/bin/env python
import subprocess
import sys
import time

# TODO: add --hang option to detect code which impacts the analysis time
def show_syntax():
    print('Syntax:')
    print('  reduce.py --cmd=<full command> --expected=<expected text output> --file=<source file> [--segfault]')
    print('')
    print("Example. source file = foo/bar.c")
    print("  reduce.py --cmd='./cppcheck --enable=style foo/bar.c' --expected=\"Variable 'x' is reassigned\" --file=foo/bar.c")
    sys.exit(1)

if len(sys.argv) == 1:
    show_syntax()

CMD = None
EXPECTED = None
SEGFAULT = False
FILE = None
ORGFILE = None
BACKUPFILE = None
TIMEOUTFILE = None
for arg in sys.argv[1:]:
    if arg.startswith('--cmd='):
        CMD = arg[arg.find('=') + 1:]
    elif arg.startswith('--expected='):
        EXPECTED = arg[arg.find('=') + 1:]
    elif arg.startswith('--file='):
        FILE = arg[arg.find('=') + 1:]
        ORGFILE = FILE + '.org'
        BACKUPFILE = FILE + '.bak'
        TIMEOUTFILE = FILE + '.timeout'
    elif arg == '--segfault':
        SEGFAULT = True

if CMD is None:
    print('Abort: No --cmd')
    show_syntax()

if not SEGFAULT and EXPECTED is None:
    print('Abort: No --expected')
    show_syntax()

# need to add '--error-exitcode=0' so detected issues will not be interpreted as a crash
if SEGFAULT and not '--error-exitcode=0' in CMD:
    print("Adding '--error-exitcode=0' to --cmd")
    CMD = CMD + ' --error-exitcode=0'

if FILE is None:
    print('Abort: No --file')
    show_syntax()

print('CMD=' + CMD)
if SEGFAULT:
    print('EXPECTED=SEGFAULT')
else:
    print('EXPECTED=' + EXPECTED)
print('FILE=' + FILE)


def runtool(filedata=None):
    timeout = None
    if elapsed_time:
        timeout = elapsed_time * 2
    p = subprocess.Popen(CMD.split(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        comm = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        print('timeout')
        p.kill()
        p.communicate()
        if filedata:
            writefile(TIMEOUTFILE, filedata)
        return False
    #print(p.returncode)
    #print(comm)
    if SEGFAULT:
        if p.returncode != 0:
            return True
    elif p.returncode == 0:
        out = comm[0] + '\n' + comm[1]
        if EXPECTED in out:
            return True
    else:
        # Something could be wrong, for example the command line for Cppcheck (CMD).
        # Print the output to give a hint how to fix it.
        print('Error: {}\n{}'.format(comm[0], comm[1]))
    return False


def writefile(filename, filedata):
    f = open(filename, 'wt')
    for line in filedata:
        f.write(line)
    f.close()


def replaceandrun(what, filedata, i, line):
    print(what + ' ' + str(i + 1) + '/' + str(len(filedata)) + '..')
    bak = filedata[i]
    filedata[i] = line
    writefile(FILE, filedata)
    if runtool(filedata):
        print('pass')
        writefile(BACKUPFILE, filedata)
        return True
    print('fail')
    filedata[i] = bak
    return False


def replaceandrun2(what, filedata, i, line1, line2):
    print(what + ' ' + str(i + 1) + '/' + str(len(filedata)) + '..')
    bak1 = filedata[i]
    bak2 = filedata[i + 1]
    filedata[i] = line1
    filedata[i + 1] = line2
    writefile(FILE, filedata)
    if runtool(filedata):
        print('pass')
        writefile(BACKUPFILE, filedata)
    else:
        print('fail')
        filedata[i] = bak1
        filedata[i + 1] = bak2


def clearandrun(what, filedata, i1, i2):
    print(what + ' ' + str(i1 + 1) + '/' + str(len(filedata)) + '..')
    filedata2 = list(filedata)
    i = i1
    while i <= i2 and i < len(filedata2):
        filedata2[i] = ''
        i = i + 1
    writefile(FILE, filedata2)
    if runtool(filedata2):
        print('pass')
        writefile(BACKUPFILE, filedata2)
        return filedata2
    print('fail')
    return filedata


def removecomments(filedata):
    for i in range(len(filedata)):
        line = filedata[i]
        if '//' in line:
            replaceandrun('remove comment', filedata, i, line[:line.find('//')].rstrip() + '\n')


def checkpar(line):
    par = 0
    for c in line:
        if c == '(' or c == '[':
            par = par + 1
        elif c == ')' or c == ']':
            par = par - 1
            if par < 0:
                return False
    return par == 0


def combinelines(filedata):
    if len(filedata) < 3:
        return

    lines = []

    for i in range(len(filedata) - 1):
        fd1 = filedata[i].rstrip()
        if fd1.endswith(','):
            fd2 = filedata[i + 1].lstrip()
            if fd2 != '':
                lines.append(i)

    chunksize = len(lines)
    while chunksize > 10:
        i = 0
        while i < len(lines):
            i1 = i
            i2 = i + chunksize
            i = i2
            if i2 > len(lines):
                i2 = len(lines)

            filedata2 = list(filedata)
            for line in lines[i1:i2]:
                filedata2[line] = filedata2[line].rstrip() + filedata2[line + 1].lstrip()
                filedata2[line + 1] = ''

            if replaceandrun('combine lines', filedata2, lines[i1] + 1, ''):
                filedata = filedata2
                lines[i1:i2] = []
                i = i1

        chunksize = chunksize / 2

    for line in lines:
        fd1 = filedata[line].rstrip()
        fd2 = filedata[line + 1].lstrip()
        replaceandrun2('combine lines', filedata, line, fd1 + fd2, '')


def removedirectives(filedata):
    for i in range(len(filedata)):
        line = filedata[i].lstrip()
        if line.startswith('#'):
            # these cannot be removed on their own so skip them
            if line.startswith('#if') or line.startswith('#endif') or line.startswith('#el'):
                continue
            replaceandrun('remove preprocessor directive', filedata, i, '')


def removeblocks(filedata):
    if len(filedata) < 3:
        return filedata

    for i in range(len(filedata)):
        strippedline = filedata[i].strip()
        if len(strippedline) == 0:
            continue
        if strippedline[-1] not in ';{}':
            continue

        i1 = i + 1
        while i1 < len(filedata) and filedata[i1].startswith('#'):
            i1 = i1 + 1

        i2 = i1
        indent = 0
        while i2 < len(filedata):
            for c in filedata[i2]:
                if c == '}':
                    indent = indent - 1
                    if indent == 0:
                        indent = -100
                elif c == '{':
                    indent = indent + 1
            if indent < 0:
                break
            i2 = i2 + 1
        if indent == -100:
            indent = 0
        if i2 == i1 or i2 >= len(filedata):
            continue
        if filedata[i2].strip() != '}' and filedata[i2].strip() != '};':
            continue
        if indent < 0:
            i2 = i2 - 1
        filedata = clearandrun('remove codeblock', filedata, i1, i2)

    return filedata


def removeline(filedata):
    stmt = True
    for i in range(len(filedata)):
        line = filedata[i]
        strippedline = line.strip()

        if len(strippedline) == 0:
            continue

        if stmt and strippedline[-1] == ';' and checkpar(line) and '{' not in line and '}' not in line:
            replaceandrun('remove line', filedata, i, '')

        elif stmt and '{' in strippedline and strippedline.find('}') == len(strippedline) - 1:
            replaceandrun('remove line', filedata, i, '')

        if strippedline[-1] in ';{}':
            stmt = True
        else:
            stmt = False


# reduce..
print('Make sure error can be reproduced...')
elapsed_time = None
t = time.perf_counter()
if not runtool():
    print("Cannot reproduce")
    sys.exit(1)
elapsed_time = time.perf_counter() - t
print('elapsed_time: {}'.format(elapsed_time))

f = open(FILE, 'rt')
filedata = f.readlines()
f.close()

writefile(ORGFILE, filedata)

while True:
    filedata1 = list(filedata)

    print('remove preprocessor directives...')
    removedirectives(filedata)

    print('remove blocks...')
    filedata = removeblocks(filedata)

    print('remove comments...')
    removecomments(filedata)

    print('combine lines..')
    combinelines(filedata)

    print('remove line...')
    removeline(filedata)

    # if filedata and filedata2 are identical then stop
    if filedata1 == filedata:
        break

writefile(FILE, filedata)
print('DONE')
