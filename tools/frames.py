import struct,sys,datetime
d=open(sys.argv[1],'rb').read()[24:]
o=0;ev=[]
while o+16<=len(d):
    s,u,cl,ol=struct.unpack_from('<IIII',d,o);o+=16
    b=d[o:o+cl];o+=cl
    typ=chr(b[8]);ep=b[10]
    if typ=='S' and not ep&0x80: ev.append((s+u/1e6,'OUT',b[48:]))
    if typ=='C' and ep&0x80 and struct.unpack_from('<i',b,28)[0]==0: ev.append((s+u/1e6,'IN',b[48:]))
# frames: start 5c 3c, end 5c 3e, 5c 5c = escaped 5c; reassembled per direction
def frames(chunks):
    buf=b''.join(chunks);out=[];i=0;cur=None
    while i<len(buf)-1:
        a,c=buf[i],buf[i+1]
        if a==0x5c:
            if c==0x3c: cur=bytearray();i+=2;continue
            if c==0x3e:
                if cur is not None: out.append(bytes(cur));cur=None
                i+=2;continue
            if c==0x5c:
                if cur is not None: cur.append(0x5c)
                i+=2;continue
        if cur is not None: cur.append(a)
        i+=1
    return out
# keep the order: frames with their time
res=[];t0=ev[0][0]
for dr in ('OUT','IN'):
    pass
cur={'OUT':[],'IN':[]}
seq=[]
for t,dr,data in ev:
    cur[dr].append(data)
    fr=frames(cur[dr])
    # detect newly completed frames
    done=getattr(frames,'n'+dr,0)
    for f in fr[done:]: seq.append((t-t0,dr,f))
    setattr(frames,'n'+dr,len(fr))
for t,dr,f in seq:
    print(f"{t:8.3f} {dr:3s} cmd=0x{f[0]:02x} len={len(f):4d}  {f[:48].hex(' ')}")
import pickle;pickle.dump(seq,open(sys.argv[2],'wb'))
