import itertools
import time
import os
import random

import spotipy
from spotipy.oauth2 import SpotifyOAuth
import spotipy.util

from . import app, log
from .util import dict_get_nested, shrink_nested_list, chunked

TRACK_LIMIT = 10000


def get_spotify_oauth():
    client_id = os.getenv('SPOTIPY_CLIENT_ID')
    client_secret = os.getenv('SPOTIPY_CLIENT_SECRET')
    redirect_uri = os.getenv('SPOTIPY_REDIRECT_URI')
    log.info(app.config['SPOTIFY_AUTHORIZATION_SCOPE'])
    auth = ExtendedOAuth(
        client_id, client_secret, redirect_uri,
        scope=app.config['SPOTIFY_AUTHORIZATION_SCOPE'])
    return auth


def token_is_expired(token):
    return token['expires_at'] < time.time()


def refresh_token(token):
    if token_is_expired(token):
        log.info('Token expired, refreshing:{}'.format(token['access_token']))
        auth = get_spotify_oauth()
        return auth._refresh_access_token(token['refresh_token'])
    else:
        return token


class ExtendedOAuth(SpotifyOAuth):
    def __init__(self, *args, **kwargs):
        SpotifyOAuth.__init__(self, *args, **kwargs)
        self.token_info = None

    def get_access_token(self, code):
        """
        Overrides get_access_token to store
        the token in an instance variable after creation.
        """
        self.token_info = SpotifyOAuth.get_access_token(
            self, code)
        return self.token_info

    def get_stored_token(self):
        """
        Get self.token_info, refreshing the token if needed.
        """
        is_expired = self._is_token_expired(self.token_info)
        if self.token_info:
            if is_expired:
                self.token_info = self._refresh_access_token(
                    self.token_info['refresh_token'])
            return self.token_infon


def iterate_results(spotify, endpoint, *args, **kwargs):
    sp = spotify
    func = getattr(sp, endpoint)
    try:
        target_key = kwargs.pop('target_key')
    except KeyError:
        target_key = 'items'
    try:
        next_key = kwargs.pop('next_key')
    except KeyError:
        next_key = 'next'

    result = func(*args, **kwargs)
    while True:
        itemlist = dict_get_nested(target_key, result)
        for item in itemlist:
            yield item
        try:
            next_url = dict_get_nested(next_key, result)
        except KeyError:
            break
        if next_url:
            result = sp._get(next_url)
        else:
            break


def get_current_user(access_token):
    return spotipy.Spotify(auth=access_token).current_user()


def get_saved_tracks(access_token):
    spotify = spotipy.Spotify(auth=access_token)
    return iterate_results(spotify, 'current_user_saved_tracks', limit=50)


def get_top(access_token, top_type='artists', time_range='medium_term'):
    spotify = spotipy.Spotify(auth=access_token)
    endpoint = 'current_user_top_{}'.format(top_type)
    return iterate_results(spotify,
                           endpoint,
                           time_range=time_range,
                           limit=50)


def get_all_top(access_token, top_type='artists'):
    return itertools.chain(
        get_top(access_token, top_type=top_type, time_range='short_term'),
        get_top(access_token, top_type=top_type, time_range='medium_term'),
        get_top(access_token, top_type=top_type, time_range='long_term'))


def get_followed_artists(access_token):
    spotify = spotipy.Spotify(auth=access_token)
    return iterate_results(spotify,
                           'current_user_followed_artists',
                           target_key=['artists', 'items'],
                           next_key=['artists', 'next'],
                           limit=50)


def get_saved_album_artists(access_token):
    spotify = spotipy.Spotify(auth=access_token)
    albums = iterate_results(spotify,
                             'current_user_saved_albums',
                             limit=50)
    for album in albums:
        for artist in album['album']['artists']:
            yield artist


def get_recommendations(access_token, seed_artists, limit=100, **kwargs):
    artist_ids = list(set([a['id'] for a in seed_artists]))
    log.info('Number of artists used as seed:{}'.format(len(artist_ids)))

    spotify = spotipy.Spotify(auth=access_token)
    endpoint = 'recommendations'
    gens = []
    for artist in artist_ids:
        gens.append(
            iterate_results(spotify,
                            endpoint,
                            target_key='tracks',
                            seed_artists=[artist],
                            limit=limit,
                            **kwargs))
    log.info('Number of track generators:{}'.format(len(gens)))
    return gens
    return itertools.chain(*gens)


class PlaylistGenerator(object):
    def __init__(self, access_token, **kwargs):
        self.access_token = access_token
        self.spotify = spotipy.Spotify(auth=access_token)
        self.user = self.spotify.current_user()
        self.playlist_name = kwargs.get('playlist_name',
                                        'Spotifetch generated playlist')
        self.tuneable = kwargs.get('tuneable', {})
        self.top_artists_time_range = kwargs.get(
            'top_artists_time_range', [])
        self.followed_artists = kwargs.get('followed_artists', False)
        self.saved_album_artists = kwargs.get('saved_album_artists', False)
        self.single_recommendation_limit = 50

    def get_seed_artists(self):
        gens = []
        for tr in self.top_artists_time_range:
            gens.append(
                get_top(self.access_token,
                        top_type='artists', time_range=tr))
        if self.followed_artists:
            gens.append(
                get_followed_artists(self.access_token))
        if self.saved_album_artists:
            gens.append(
                get_saved_album_artists(self.access_token))
        return itertools.chain(*gens)

    def get_recommendations(self, seed_artists):
        artist_ids = list(set([a['id'] for a in seed_artists]))
        log.info('Number of artists used as seed:{}'.format(len(artist_ids)))
        recommendations = []

        added = set()

        for artist in artist_ids:
            log.info('Getting recommendations for artist:{}'.format(artist))
            recs = iterate_results(self.spotify,
                                   'recommendations',
                                   target_key='tracks',
                                   seed_artists=[artist],
                                   limit=self.single_recommendation_limit,
                                   **self.tuneable)
            l = []
            for track in recs:
                tid = track['id']
                if tid in added:
                    continue
                added.add(tid)
                l.append(tid)

            recommendations.append(l)
        return recommendations

    def get_track_list(self, recs):
        log.info('Total tracks before shrink:{}'.format(
            sum([len(l) for l in recs])))
        recs = shrink_nested_list(
            recs,
            limit=TRACK_LIMIT)
        recs = list(itertools.chain(*recs))
        random.shuffle(recs)
        return recs

    def create_playlist(self):
        return self.spotify.user_playlist_create(
            self.user['id'], self.playlist_name, public=True)

    def add_to_playlist(self, playlist, tracks):
        count = 0
        for chunk in chunked(tracks, 50):
            time.sleep(0.3)
            self.spotify.user_playlist_add_tracks(
                self.user['id'], playlist['id'], chunk)
            count += len(chunk)
        log.info('{} tracks added to {}'.format(
            count, playlist['uri']))

    def generate_playlist(self):
        log.info('User:"{}" starts generating playlist'.format(
            self.user['id']))

        playlist = self.create_playlist()

        log.info('Playlist:"{}" created'.format(playlist['uri']))
        log.info('Begin getting seeds')

        seeds = self.get_seed_artists()

        log.info('Begin getting recommendations')

        recs = self.get_recommendations(seeds)

        log.info('Playlist:"{}" Total seeds:{}'.format(
            playlist['uri'], len(recs)))

        tracks = self.get_track_list(recs)

        log.info('Playlist:"{}" Total tracks after shrink:{}'.format(
            playlist['uri'], len(tracks)))

        log.info('Playlist:"{}" begin adding tracks'.format(
            playlist['uri']))

        self.add_to_playlist(playlist, tracks)

        # log.info('{} tracks added to {}'.format(
        #     playlist['uri'], len(tracks)))

        return playlist['uri']
