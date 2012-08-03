#!/usr/bin/env python
## category General
## desc Calculates simple stats for a BAM file
"""
Calculates simple stats for a BAM file
"""

import os
import sys
import pysam
from bam import read_calc_mismatches
from support.eta import ETA
from support.ngs_utils import natural_sort
from support.regions import RegionTagger


class FeatureBin(object):
    '''track feature stats'''
    def __init__(self, tag):
        spl = tag.split(':')
        self.tag = spl[0]
        self.asc = True
        if len(spl) > 1:
            self.asc = True if spl[1] == '+' else False

        self.bins = {}
        self._keys = []
        self._min = None
        self._max = None
        self.__cur_pos = -1
        self.missing = 0

    def __iter__(self):
        self._keys.sort()
        if not self.asc:
            self._keys.reverse()

        self.__cur_pos = -1
        return self

    def next(self):
        self.__cur_pos += 1
        if len(self._keys) <= self.__cur_pos:
            raise StopIteration
        else:
            return (self._keys[self.__cur_pos], self.bins[self._keys[self.__cur_pos]])

    @property
    def mean(self):
        acc = 0
        count = 0
        for k in self.bins:
            try:
                acc += (k * self.bins[k])
                count += self.bins[k]
            except:
                return 0

        return float(acc) / count

    @property
    def max(self):
        return self._max

    def add(self, read):
        if self.tag in ['LENGTH', 'LEN']:
            val = len(read.seq)
        elif self.tag == 'MAPQ':
            val = read.mapq
        elif self.tag == 'MISMATCH':
            val = read_calc_mismatches(read)
        else:
            try:
                val = read.opt(self.tag)
            except KeyError:
                self.missing += 1
                return

        if not val in self.bins:
            self.bins[val] = 0
            self._keys.append(val)

        self.bins[val] += 1
        if not self._min or self._min > val:
            self._min = val
        if not self._max or self._max < val:
            self._max = val


def usage():
    print __doc__
    print """
Usage: bamutils stats in.bam {options} {region}

If a region is given, only reads that map to that region will be counted.
Regions should be be in the format: 'ref:start-end' or 'ref:start' using
1-based start coordinates.

Options:
    -tags   tag_name{:sort_order},tag_name{:sort_order},...

            For each tag that is given, the values for that tag will be
            tallied for all reads. Then a list of the counts will be presented
            along with the mean and maximum values. The optional sort order
            should be either '+' or '-' (defaults to +).

            There are also special case tags that can be used as well:
                MAPQ     - use the mapq score
                LENGTH   - use the length of the read
                MISMATCH - use the mismatch score (# mismatches) + (# indels)
                           where indels count for 1 regardless of length

                           Note: this requires the 'NM' tag (edit distance)
                           to be present

            Common tags:
                AS    Alignment score
                IH    Number of alignments
                NM    Edit distance (each indel counts as many as its length)

            For example, to tally the "IH" tag (number of alignments) and the
            read length:
                -tags IH,LENGTH


    -delim  char

            If delimiter is given, the reference names are split by this
            delimiter and only the first token is summarized.

    -gtf model.gtf

            If a GTF gene model is given, counts corresponding to exons,
            introns, promoters, junctions, intergenic, and mitochondrial
            regions will be calculated.
"""
    sys.exit(1)

flag_descriptions = {
0x1: 'Multiple fragments',
0x2: 'All fragments aligned',
0x4: 'Unmapped',
0x8: 'Next unmapped',
0x10: 'Reverse complimented',
0x20: 'Next reverse complimented',
0x40: 'First fragment',
0x80: 'Last fragment',
0x100: 'Secondary alignment',
0x200: 'QC Fail',
0x400: 'PCR/Optical duplicate'
}


def bam_stats(infile, gtf_file=None, region=None, delim=None, tags=[]):
    bamfile = pysam.Samfile(infile, "rb")
    eta = ETA(0, bamfile=bamfile)

    regiontagger = None
    flag_counts = {}

    ref = None
    start = None
    end = None

    if gtf_file:
        regiontagger = RegionTagger(gtf_file, bamfile.references)

    if region:
        ref, startend = region.split(':')
        if '-' in startend:
            start, end = [int(x) for x in startend.split('-')]
            start = start - 1
            sys.stderr.write('Region: %s:%s-%s\n' % (ref, start + 1, end))
        else:
            start = int(startend) - 1
            end = int(startend)
            sys.stderr.write('Region: %s:%s\n' % (ref, start + 1))

    total = 0
    mapped = 0
    unmapped = 0
    names = set()
    refs = {}

    tagbins = []
    for tag in tags:
        tagbins.append(FeatureBin(tag))

    for rname in bamfile.references:
        if delim:
            refs[rname.split(delim)[0]] = 0
        else:
            refs[rname] = 0

    # setup region or whole-file readers
    def _foo1():
        for read in bamfile.fetch(ref, start, end):
            yield read

    def _foo2():
        for read in bamfile:
            yield read

    if region:
        read_gen = _foo1
    else:
        read_gen = _foo2

    sys.stderr.write('Calculating Read stats...\n')
    try:
        for read in read_gen():
            try:
                if read.opt('IH') > 1:
                    if read.qname in names:
                        # reads only count once for this...
                        continue
                    names.add(read.qname)
            except KeyError:
                #missing IH tag - ignore
                pass

            if not read.flag in flag_counts:
                flag_counts[read.flag] = 1
            else:
                flag_counts[read.flag] += 1

            total += 1
            if read.is_unmapped:
                unmapped += 1
                continue

            eta.print_status(extra="%s:%s" % (bamfile.getrname(read.rname), read.pos), bam_pos=(read.rname, read.pos))
            mapped += 1

            if delim:
                refs[bamfile.getrname(read.rname).split(delim)[0]] += 1
            else:
                refs[bamfile.getrname(read.rname)] += 1

            if regiontagger:
                regiontagger.add_read(read, bamfile.getrname(read.rname))

            for tagbin in tagbins:
                tagbin.add(read)

    except KeyboardInterrupt:
        sys.stderr.write('*** Interrupted - displaying stats up to this point! ***\n\n')

    eta.done()

    print "Reads:\t%s" % total
    print "Mapped:\t%s" % mapped
    print "Unmapped:\t%s" % unmapped

    if total > 0:
        print ""
        print "Flag distribution"

        tmp = []
        maxsize = 0
        for flag in flag_descriptions:
            if flag in flag_counts:
                tmp.append(flag)
                maxsize = max(maxsize, len(flag_descriptions[flag]))
        tmp.sort()

        for flag in tmp:
            count = 0
            for f in flag_counts:
                if (f & flag) > 0:
                    count += flag_counts[f]

            if count > 0:
                print "[0x%03x] %-*s:\t%s\t%.1f%%" % (flag, maxsize, flag_descriptions[flag], count, (float(count) * 100 / total))

        print ""
        print ""

        for tagbin in tagbins:
            print "Ave %s:\t%s" % (tagbin.tag, tagbin.mean)
            print "Max %s:\t%s" % (tagbin.tag, tagbin.max)
            if tagbin.missing:
                print 'Missing %s:\t%s' % (tagbin.tag, tagbin.missing)

            print "%s distribution:" % (tagbin.tag)

            acc = 0.0
            for val, count in tagbin:
                acc += count
                pct = acc * 100 / mapped
                print '%s\t%s\t%.1f%%' % (val, count, pct)

            print ""

        print "Reference distribution"
        if delim:
            print "ref\tcount"
            for refname in natural_sort(refs):
                print "%s\t%s" % (refname, refs[refname])
        else:
            print "ref\tlength\tcount\tcount per million bases"
            reflens = {}
            for refname, reflen in zip(bamfile.references, bamfile.lengths):
                reflens[refname] = reflen

            for refname in natural_sort(refs):
                print "%s\t%s\t%s\t%s" % (refname, reflens[refname], refs[refname], refs[refname] / (float(reflens[refname]) / 1000000))

        if regiontagger:
            print ""
            print "Mapping regions"
            sorted_keys = [x for x in regiontagger.counts]
            sorted_keys.sort()
            for k in sorted_keys:
                print "%s\t%s" % (k, regiontagger.counts[k])

    bamfile.close()


if __name__ == '__main__':
    infile = None
    gtf = None
    region = None
    delim = None
    tags = []

    last = None
    for arg in sys.argv[1:]:
        if arg == '-h':
            usage()
        elif not infile and os.path.exists(arg):
            infile = arg
        elif last == '-gtf':
            gtf = arg
            last = None
        elif last == '-delim':
            delim = arg
            last = None
        elif last == '-tags':
            tags = arg.split(',')
            last = None
        elif arg in ['-gtf', '-delim', '-tags']:
            last = arg
        elif ':' in arg:
            region = arg
        else:
            sys.stderr.write('Unknown option: %s\n' % arg)
            usage()

    if not infile:
        usage()
    else:
        bam_stats(infile, gtf, region, delim, tags)