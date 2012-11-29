
import sys
import os
import gzip
import math
import collections
from eta import ETA


FASTQRead = collections.namedtuple('FASTQRead', 'name seq qual')


class FASTQ(object):
    def __init__(self, fname=None, fileobj=None):
        self.fname = fname
        self._is_paired = None
        self._is_colorspace = None

        if fileobj:
            self.fileobj = fileobj
        elif fname:
            if fname == '-':
                self.fileobj = sys.stdin
            elif fname[-3:] == '.gz' or fname[-4:] == '.bgz':
                self.fileobj = gzip.open(os.path.expanduser(fname))
            else:
                self.fileobj = open(os.path.expanduser(fname))
        else:
            raise ValueError("Must pass either a fileobj or fname!")

    def tell(self):
        # always relative to uncompressed...
        return self.fileobj.tell()

    def seek(self, pos, whence=0):
        self.fileobj.seek(pos, whence)

    def fetch(self, quiet=False):
        if self.fname and not quiet:
            eta = ETA(os.stat(self.fname).st_size, fileobj=self.fileobj)
        else:
            eta = None

        while True:
            try:
                name = self.fileobj.next().strip()[1:]
                seq = self.fileobj.next().strip()
                self.fileobj.next()
                qual = self.fileobj.next().strip()

                if eta:
                    eta.print_status(name)
                yield FASTQRead(name, seq, qual)

            except:
                break

        if eta:
            eta.done()

    def close(self):
        if self.fileobj != sys.stdout:
            self.fileobj.close()

    def check_qualtype(self, num_to_check=10000):
        '''
        Checks a FASTQ file's quality score to see what encoding/scaling is used:
        Sanger, Solexa, or Illumina

        returns "Sanger", "Solexa", "Illumina", or "Unknown"
        '''

        # these are the differential values, unscaled from chr()
        sanger = (33, 74)  # default sanger is 0->40, but some newer illumina on this scale is 0->41
        solexa = (59, 104)
        illumina = (64, 104)

        sanger_count = 0
        solexa_count = 0
        illumina_count = 0
        unknown_count = 0

        checked = 0
        for read in self.fetch(quiet=True):
            if checked > num_to_check:
                break
            qmax = None
            qmin = None
            for q in [ord(x) for x in read.qual]:
                if qmin is None or q < qmin:
                    qmin = q
                if qmax is None or q > qmax:
                    qmax = q

            if sanger[0] <= qmin <= qmax <= sanger[1]:
                sanger_count += 1
            elif illumina[0] <= qmin <= qmax <= illumina[1]:
                illumina_count += 1
            elif solexa[0] <= qmin <= qmax <= solexa[1]:
                solexa_count += 1
            else:
                unknown_count += 1
            checked += 1

        self.seek(0)

        if unknown_count > 0:
            return 'Unknown'  # We don't have any idea about at least one of these reads

        if solexa_count > 0:
            # If there are any reads that fall in the Solexa range,
            # this must be a Solexa scale file. This should be rare.
            return 'Solexa'

        if sanger_count > illumina_count:
            return 'Sanger'
        return 'Illumina'

    @property
    def is_colorspace(self):
        '''
        This works by scanning the first 10 reads that have sequences (aren't Ns
        or 4s). If there are any colorspace values, the entire file is called as
        colorspace.

        It's a bit overkill...
        '''

        if self._is_colorspace is not None:
            return self._is_colorspace

        pos = self.tell()
        self.seek(0)
        self._is_colorspace = None

        valid_basespace = "atcgATCG"
        valid_colorspace = "0123456"

        for read in self.fetch(quiet=True):
            if len(read.seq) < 2:
                continue

            for base in read.seq[1:]:  # skip the first base, in case there is a linker prefix
                if base in valid_colorspace:
                    self._is_colorspace = True
                    break
                elif base in valid_basespace:
                    self._is_colorspace = False
                    break
            if self._is_colorspace is not None:
                break

        self.seek(pos)
        return self._is_colorspace

    @property
    def is_paired(self):
        '''
        Determines if a FASTQ file has paired reads. This returns True is the file has
        paired reads with the same name in consecutive order.
        '''

        if self._is_paired is not None:
            return self._is_paired

        pos = self.tell()
        self.seek(0)
        last_name = None
        count = 0

        for read in self.fetch(quiet=True):
            name = read.name.split()[0]
            if last_name:
                if name == last_name:
                    count += 1
                else:
                    self._is_paired = count > 1
                    self.seek(pos)

                    return self._is_paired
            else:
                last_name = name
                count = 1

        # if there are only 2 reads...
        self._is_paired = count > 1
        self.seek(pos)
        return self._is_paired


# def read_fastq(fname, quiet=False, eta_callback=None):
#     with ngsutils.support.ngs_utils.gzip_opener(fname) as f:
#         if fname == '-':
#             quiet = True
#         if not quiet:
#             eta = ETA(os.stat(fname).st_size, fileobj=f)
#         while f:
#             try:
#                 name = f.next().strip()
#                 seq = f.next().strip()
#                 f.next()
#                 qual = f.next().strip()

#                 if eta_callback:
#                     extra = eta_callback()
#                 else:
#                     extra = name
#                 if not quiet:
#                     eta.print_status(extra=extra)
#                 yield (name, seq, qual)
#             except:
#                 break
#     if not quiet:
#         eta.done()

def convert_illumina_qual(qual):
    '''
    Illumina char: QPhred + 64
    Phred char: QPhred + 33
    '''

    return ''.join([chr(ord(q) - 31) for q in qual])


def convert_solexa_qual(qual):
    '''
    Illumina char: QSolexa + 64  (note: this is for very old samples)
    Phred char: QPhred + 33

    QPhred = -10 * log10 (1/error)
    QSolexa = -10 * log10 (error/(1-error))

    QPhred = 10 * log10 (10 ^ (QSolexa/10) + 1)

    '''

    rv = []
    for q in qual:
        val = ord(q) - 64
        qp = int(10 * math.log10(10 ** (val / 10) + 1))
        rv.append(chr(qp + 33))
    return ''.join(rv)
