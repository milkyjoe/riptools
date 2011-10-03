#!/usr/bin/env python
#
# Copyright (c) 2011 Milky Joe <milkiejoe@gmail.com>
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import sys
import argparse
import subprocess
import re
import logging
import os
import contextlib

eac3to = 'C:\Program Files (x86)\eac3to\eac3to.exe'

logger = logging.getLogger('eac3bot')

def find_track_matches(regex, track_list):
    def match(track):
        m = re.match(regex, track)
        if m:
            return m.groupdict()
        else:
            return None
    return filter(lambda x: x, map(match, track_list))

def filter_by(regexes, tracks):
    selected_tracks = []
    for r in regexes:
        selected_tracks += filter(lambda t: re.search(r, t['description']),
                                  tracks)
    return selected_tracks

def chapter_tracks(track_list):
    return find_track_matches(r'(?P<id>[0-9]+:) (?P<description>Chapters, .*)',
                              track_list)

def video_tracks(track_list):
    all_tracks = find_track_matches(r'(?P<id>[0-9]+:) (?P<description>h264/AVC, 1080p24 /1.001 \(16:9\)$)', track_list)
    all_tracks += find_track_matches(r'(?P<id>[0-9]+:) (?P<description>VC-1, 1080p24 /1.001 \(16:9\)$)', track_list)
    return all_tracks

def lossless_audio_tracks(track_list, languages=[r'English']):
    all_tracks = find_track_matches(r'(?P<id>[0-9]+:) (?P<description>DTS Master Audio, .*)',
                                    track_list)
    all_tracks += find_track_matches(r'(?P<id>[0-9]+:) (?P<description>TrueHD/AC3, .*)',
                                    track_list)
    return filter_by(languages, all_tracks)

def lossy_audio_tracks(track_list, languages=[r'English'], channels=[r'[12]\.0']):
    all_tracks = find_track_matches(r'(?P<id>[0-9]+:) (?P<description>AC3, .*)', track_list)
    all_tracks += find_track_matches(r'(?P<id>[0-9]+:) (?P<description>AC3 Surround, .*)', track_list)
    all_tracks += find_track_matches(r'(?P<id>[0-9]+:) (?P<description>DTS, .*)', track_list)
    return filter_by(channels, filter_by(languages, all_tracks))
                      
def subtitle_tracks(track_list, languages=['English']):
    all_tracks = find_track_matches(r'(?P<id>[0-9]+:) (?P<description>Subtitle \(PGS\), .*)',
                                    track_list)
    return filter_by(languages, all_tracks)

@contextlib.contextmanager
def chdir(dirname=None):
    curdir = os.getcwd()
    try:
        if dirname is not None:
            os.chdir(dirname)
        yield
    finally:
        os.chdir(curdir)
    
def demux(path, playlist_indexes=None, default_audio_track=None):
    #
    # Scan for playlists.
    #
    logger.info('Scanning playlists in %s' % path)
    try:
        scan_output = subprocess.check_output([eac3to, path],
                                              stderr=subprocess.STDOUT)
    except:
        logger.error("%s doesn't appear to be a valid Blu-ray structure." \
                         % path)
        return 1
    lines = [line.strip('\x08').rstrip(' ') for line in \
                 scan_output.split('\r\n')]
    playlist_ids = []
    durations = []
    for line in lines:
        m = re.match(r'(?P<id>[0-9]+)\) .*, (?P<duration>[0-9]:[0-9][0-9]:[0-9][0-9])$', line)
        if m:
            playlist_ids.append(int(m.group('id')))
            durations.append(m.group('duration'))
    if not playlist_ids:
        logger.error("Can't parse eac3to output, aborting.")
        return 1

    zipped = zip(playlist_ids, durations)
    logger.info('The Blu-ray has the following playlists:')
    for (pl, dur) in zipped:
        logger.info('%d) duration: %s' % (pl, dur))

    #
    # Select playlist(s) for demuxing.
    #
    demux_playlists = []
    if playlist_indexes:
        if playlist_indexes == "all":
            demux_playlists = playlist_ids
        else:
            for idx in playlist_indexes:
                if idx not in playlist_ids:
                    logger.error("There is no playlist %d, aborting." % idx)
                    return 1
            demux_playlists = playlist_indexes
    else:
        #
        # Sort playlists by duration, choose the longest one.
        #
        zipped.sort(key=lambda p: p[1], reverse=True)
        if len(zipped) > 1 and zipped[0][1] == zipped[1][1]:
            logging.error("No obvious title track, aborting.")
            return 1
        else:
            demux_playlists = [zipped[0][0]]
            logger.info("Automatically demuxing the longest playlist (%d)" \
                             % zipped[0][0])

    for current_playlist in demux_playlists:
        demux_dir = "playlist_%02d" % current_playlist
        if not os.path.isdir(demux_dir):
            os.mkdir(demux_dir)
        os.chdir(demux_dir)
        logger.info("\nScanning playlist %d)" % current_playlist)
        try:
            pl_output = subprocess.check_output([eac3to,
                                                 path,
                                                 "%d)" % current_playlist],
                                                stderr=subprocess.STDOUT)
        except:
            logger.error("Can't parse playlist %d)" % current_playlist)
            return 1
        logger.info(pl_output)

        #
        # Select tracks to extract.
        #
        tracks = [line.strip('\x08').rstrip(' ') for line in \
                      pl_output.split('\r\n')]
        chapters = chapter_tracks(tracks)
        videos = video_tracks(tracks)
        lossless = lossless_audio_tracks(tracks)
        commentaries = lossy_audio_tracks(tracks)
        subtitles = subtitle_tracks(tracks)

        # Sanity checks for required tracks.
        if not chapters:
            logger.error("No chapter tracks found, aborting.")
            return 1
        if len(chapters) > 1:
            logger.error("There's more than one chapter track, aborting.")
            return 1
        if not videos:
            logger.error("No feature video tracks found, aborting.")
            return 1
        if len(videos) > 1:
            logger.error("There's more than one feature video track, aborting.")
            return 1
        if not lossless:
            logger.error("No lossless soundtracks selected, aborting.")
            return 1

        # I always convert lossless tracks to FLAC.
        soundtracks = []
        FLACTAG = '(FLAC)'
        for track in lossless:
            soundtracks.append({'id' : track['id'],
                                'description' : ' '.join([FLACTAG, track['description']])})
            soundtracks.append(track)

        def log_tracks(track_type, tracks):
            logger.info("  %s:" % track_type)
            if not tracks:
                logger.info("    none")
            else:
                for track in tracks:
                    logger.info("    %s %s" % (track['id'], track['description']))
            return
        logger.info("Demuxing the following tracks:")
        log_tracks("Chapters", chapters)
        log_tracks("Video", videos)
        log_tracks("Soundtracks", soundtracks)
        log_tracks("Commentaries", commentaries)
        log_tracks("Subtitles", subtitles)
        logger.info('')

        #
        # Map tracks to filenames for extraction.
        #
        def idnum(track):
            return int(track['id'].rstrip(':'))

        for track in chapters:
            track['filename'] = '%02dchapters.txt' % idnum(track)
        for track in videos:
            track['filename'] = '%02dvideo.mkv' % idnum(track)
        for track in soundtracks:
            # XXX handle these more gracefully.
            if re.search(r'strange setup', track['description']):
                logger.error("Track %d is a 'strange setup', aborting." % track['id'])
                return 1
            elif re.search(r'6.1 channels', track['description']):
                logger.error("Track %d is a 6.1-channel track, aborting." % track['id'])
                return 1

            if re.match(r'\(FLAC\)', track['description']):
                track['filename'] = '%02daudio.flac' % idnum(track)
                track['format'] = 'FLAC'
            elif re.match(r'DTS Master Audio', track['description']):
                track['filename'] = '%02daudio.dts' % idnum(track)
                track['format'] = 'DTS-MA'
            elif re.match(r'TrueHD', track['description']):
                track['filename'] = '%02daudio.thd' % idnum(track)
                track['format'] = 'TrueHD'
            else:
                # XXX handle these more gracefully
                logger.error("Audio track %d has an unknown type: %s" % (track['id'], track['description']))
                return 1
            track['channels'] = re.search(r'(?P<channels>[1-7]\.[0-2] channels)', track['description']).group('channels')
        for track in commentaries:
            if re.match(r'AC3', track['description']):
                track['filename'] = '%02dcommentary.ac3' % idnum(track)
                track['format'] = 'AC3'
            elif re.match(r'DTS', track['description']):
                track['filename'] = '%02dcommentary.dts' % idnum(track)
                track['format'] = 'DTS'
            else:
                # XXX hack.
                logger.error("Commentary track %s has unknown type: %s" % (track['id'], track['description']))
                return 1
            track['channels'] = re.search(r'(?P<channels>[1-7]\.[0-2] channels)', track['description']).group('channels')
            # Keep dialog normalization for commentaries.
            if re.search(r'dialnorm', track['description']):
                track['eac3to args'] = ['-keepDialnorm']
        for track in subtitles:
            track['filename'] = '%02dsubtitles.sup' % idnum(track)

        if default_audio_track is None:
            # assume default audio track is the first soundtrack
            default_audio_track = soundtracks[0]['id']
        else:
            if default_audio_track not in [track['id'].rstrip(':') for track in soundtracks] and \
                    default_audio_track not in [track['id'].rstrip(':') for track in commentaries]:
                logger.error("You selected track ID %s as the default audio track, but it's not an audio track; aborting." % default_audio_track)
                return 1
            
        eac3to_command = [eac3to, path, '%d)' % current_playlist]
        for lst in [chapters, videos, soundtracks, commentaries, subtitles]:
            for track in lst:
                eac3to_command.append(track['id'])
                eac3to_command.append(track['filename'])
                if 'eac3to args' in track:
                    # eac3to args are a list.
                    eac3to_command += track['eac3to args']

        logger.info('')
        logger.info("Demuxing command line: %s", ' '.join(eac3to_command))

        rc = subprocess.call(eac3to_command)
        if rc:
            return rc

        mkvmerge_options = ['# Set default language']
        mkvmerge_options += ['--default-language', 'eng']
        # eac3to always saves the log file as 'foo - Log.txt' where 'foo'
        # is the filename of the first extracted track, minus the '.txt'
        # extension. In our case, that's the chapter file.
        mkvmerge_options += ['', '# Attach eac3to extraction log']
        mkvmerge_options += ['--attachment-description', 'eac3to extraction log',
                             '--attachment-mime-type', 'text/plain',
                             '--attach-file', '%s - Log.txt' % chapters[0]['filename'].rstrip('.txt')]
        mkvmerge_options += ['', '# Chapter file']
        for track in chapters:
            mkvmerge_options += ['--chapters', track['filename']]
        # XXX hack - assume first video track is the default
        mkvmerge_options += ['', '# Default video track']
        mkvmerge_options += ['--default-track', '-1:1',
                             '--track-name', '-1:Theatrical release',
                             videos[0]['filename']]
        mkvmerge_options += ['', '# Additional video tracks (may be empty)']
        for track in videos[1:]:
            mkvmerge_options += ['--default-track', '-1:0', track['filename']]

        mkvmerge_options += ['', '# Soundtracks']
        for track in soundtracks:
            if track['id'].rstrip(':') == default_audio_track:
                dta = '-1:1'
                # XXX hack: now reset default track so that if there's
                # more than one track with the same id (e.g. a DTS-MA
                # version of a FLAC track), we won't end up with two
                # tracks marked as default.
                default_audio_track = 0
            else:
                dta = '-1:0'
            mkvmerge_options += ['--default-track', dta,
                                 '--track-name', '-1:%s theatrical soundtrack (%s)' % (track['format'], track['channels']),
                                 track['filename']]
        mkvmerge_options += ['', '# Commentary tracks (may be empty)']
        for track in commentaries:
            if track['id'].rstrip(':') == default_audio_track:
                dta = '-1:1'
                # XXX hack: now reset default track so that if there's
                # more than one track with the same id (e.g. a DTS-MA
                # version of a FLAC track), we won't end up with two
                # tracks marked as default.
                default_audio_track = 0
            else:
                dta = '-1:0'
            mkvmerge_options += ['--default-track', dta,
                                 '--track-name', '-1:%s commentary (%s)' % (track['format'], track['channels']),
                                 track['filename']]
        mkvmerge_options += ['', '# Subtitles (may be empty)']
        for track in subtitles:
            mkvmerge_options += ['--default-track', '-1:0',
                                 '--track-name', '-1:Subtitles',
                                 track['filename']]
        logger.info('Saving mkvmerge options to mkvmerge.options')
        mkvopts_file = open('mkvmerge.options', 'w')
        mkvopts_file.write('\n'.join(mkvmerge_options))
        mkvopts_file.close()
        os.chdir("..")
        
    logger.info('Done')
    return 0
    
def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument('--playlist', nargs='+', default=None,
                        help='Demux the given playlists (by index), or all playlists if "all" is given.')
    parser.add_argument('--default-audio-track', nargs=1, default=None,
                        help='Make the given track number the default audio track (default: automatically selected).')
    parser.add_argument('path', nargs=1)
    args = parser.parse_args(argv)

    if args.playlist is None:
        playlist_indexes = None
    else:
        if 'all' in args.playlist:
            playlist_indexes = 'all'
        else:
            try:
                playlist_indexes = [int(x) for x in args.playlist]
            except ValueError:
                print >> sys.stderr, 'Playlist indexes must be an positive integer, or "all"'
                return 1
    if args.default_audio_track is None:
        default_audio_track = None
    else:
        default_audio_track = args.default_audio_track[0]
    
    logger.setLevel(logging.INFO)
    console = logging.StreamHandler()
    logger.addHandler(console)
    
    return demux(args.path[0], playlist_indexes, default_audio_track)

if __name__ == '__main__':
    status = main()
    sys.exit(status)
