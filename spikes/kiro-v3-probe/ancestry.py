import os
def chain():
    out=[]; pid=os.getpid()
    while pid > 1 and len(out) < 12:
        try:
            stat=open(f"/proc/{pid}/stat").read(); comm=stat[stat.index("(")+1:stat.rindex(")")]
            ppid=int(stat[stat.rindex(")")+2:].split()[1])
        except OSError: break
        out.append([pid, comm]); pid=ppid
    return out
