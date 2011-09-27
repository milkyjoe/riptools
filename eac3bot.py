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
    return find_track_matches(r'(?P<id>[0-9]+:) (?P<description>h264/AVC, 1080p24 /1.001 \(16:9\)$)', track_list)

def lossless_audio_tracks(track_list, languages=[r'English']):
    all_tracks = find_track_matches(r'(?P<id>[0-9]+:) (?P<description>DTS Master Audio, .*)',
                                    track_list)
    return filter_by(languages, all_tracks)

def lossy_audio_tracks(track_list, languages=[r'English'], channels=[r'2.0']):
    all_tracks = find_track_matches(r'(?P<id>[0-9]+:) (?P<description>AC3, .*)', track_list)
    all_tracks += find_track_matches(r'(?P<id>[0-9]+:) (?P<description>AC3 Surround, .*)', track_list)
    all_tracks += find_track_matches(r'(?P<id>[0-9]+:) (?P<description>DTS, .*)', track_list)
    return filter_by(channels, filter_by(languages, all_tracks))
                      
def subtitle_tracks(track_list, languages=['English']):
    all_tracks = find_track_matches(r'(?P<id>[0-9]+:) (?P<description>Subtitle \(PGS\), .*)',
                                    track_list)
    return filter_by(languages, all_tracks)

def demux(path, user_playlist=None):
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
    playlists = []
    for line in lines:
        m = re.match(r'(?P<id>[0-9]+)\) .*, (?P<duration>[0-9]:[0-9][0-9]:[0-9][0-9])$', line)
        if m:
            playlists.append((int(m.group('id')), m.group('duration')))
    if not playlists:
        logger.error("Can't parse eac3to output, aborting.")
        return 1

    logger.info('The Blu-ray has the following playlists:')
    for pl in playlists:
        logger.info('%d) duration: %s' % (pl[0], pl[1]))

    #
    # Select playlist for demuxing.
    #
    if user_playlist:
        if user_playlist > len(playlists):
            logger.error("You specified playlist %d, but the Blu-ray only " \
                             "has %d playlists; aborting." \
                             % (user_playlist, len(playlists)))
            return 1
        else:
            logger.info("You specified playlist %d, choosing it for demuxing." \
                            % user_playlist)
            chosen_playlist = user_playlist
    else:
        #
        # Sort playlists by duration, choose the longest one.
        #
        playlists.sort(key=lambda p: p[1], reverse=True)
        if len(playlists) > 1 and playlists[0][1] == playlists[1][1]:
            logging.error("No obvious title track, aborting.")
            return 1
        else:
            chosen_playlist = playlists[0][0]
            logger.info("Automatically demuxing the longest playlist (%d)" \
                             % chosen_playlist)
    logger.info("\nScanning playlist %d)" % chosen_playlist)
    try:
        pl_output = subprocess.check_output([eac3to,
                                             path,
                                             "%d)" % chosen_playlist],
                                            stderr=subprocess.STDOUT)
    except:
        logger.error("Can't parse playlist %d)" % chosen_playlist)
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
    if len(lossless) > 1:
        logger.error("There's more than one lossless soundtrack, aborting.")
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
    # Map tracks to filenames for extraction. For easy sorting when
    # loading tracks into mkvmerge, I prefix each track with a
    # monotonically increasing integer that corresponds to its
    # relative order in the final MKV file.
    #
    prefix = 1
    eac3to_chapter_args = []
    for track in chapters:
        eac3to_chapter_args.append(track['id'])
        eac3to_chapter_args.append('%02dchapters.txt' % prefix)
        prefix += 1

    eac3to_video_args = []
    for track in videos:
        eac3to_video_args.append(track['id'])
        eac3to_video_args.append('%02dvideo.mkv' % prefix)
        prefix += 1

    eac3to_soundtrack_args = []
    for track in soundtracks:
        # XXX handle these more gracefully.
        if re.search(r'strange setup', track['description']):
            logger.error("Track %d is a 'strange setup', aborting.", track['id'])
            return 1
        elif re.search(r'6.1 channels', track['description']):
            logger.error("Track %d is a 6.1-channel track, aborting.", track['id'])
            return 1

        eac3to_soundtrack_args.append(track['id'])
        if re.match(r'\(FLAC\)', track['description']):
            eac3to_soundtrack_args.append('%02daudio.flac' % prefix)

        elif re.match(r'DTS', track['description']):
            eac3to_soundtrack_args.append('%02daudio.dts' % prefix)
        elif re.match(r'TrueHD', track['description']):
            eac3to_soundtrack_args.append('%02daudio.thd' % prefix)
        else:
            # It's a raw/PCM track, skip it.
            continue
        prefix += 1

    eac3to_commentary_args = []
    for track in commentaries:
        eac3to_commentary_args.append(track['id'])
        if re.match(r'AC3', track['description']):
            eac3to_commentary_args.append('%02dcommentary.ac3' % prefix)
        elif re.match(r'DTS', track['description']):
            eac3to_commentary_args.append('%02dcommentary.dts' % prefix)
        else:
            # XXX hack.
            logger.error("Unknown commentary track type: %s" % track['description'])
            return 1

        # Keep dialog normalization for commentaries.
        if re.search(r'dialnorm', track['description']):
            eac3to_commentary_args.append('-keepDialnorm')
        prefix += 1

    eac3to_subtitle_args = []
    for track in subtitles:
        eac3to_subtitle_args.append(track['id'])
        eac3to_subtitle_args.append('%02dsubtitles.sup' % prefix)
        prefix += 1

    eac3to_command = [eac3to, path, '%d)' % chosen_playlist]
    eac3to_command += eac3to_chapter_args
    eac3to_command += eac3to_video_args
    eac3to_command += eac3to_soundtrack_args
    eac3to_command += eac3to_commentary_args
    eac3to_command += eac3to_subtitle_args

    logger.info('')
    logger.info("Demuxing command line: %s", ' '.join(eac3to_command))
    return 0
    return subprocess.call(eac3to_command)
    
def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument('--playlist', type=int, nargs=1, default=None,
                        help='demux the given playlist index')
    parser.add_argument('path', nargs=1)
    args = parser.parse_args(argv)
    if args.playlist is None:
        user_playlist = None
    else:
        user_playlist = args.playlist[0]

    logger.setLevel(logging.INFO)
    console = logging.StreamHandler()
    logger.addHandler(console)
    
    return demux(args.path[0], user_playlist)

if __name__ == '__main__':
    status = main()
    sys.exit(status)
