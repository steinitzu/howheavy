import os

SECRET_KEY = os.getenv('HOWHEAVY_SECRET_KEY')
LOG_DIRECTORY = os.getenv('HOWHEAVY_LOG_DIRECTORY')

TEMPLATES_AUTO_RELOAD = True

auth_scopes = [
    'user-library-read',
    'user-top-read',
    'user-follow-read',
    'playlist-modify-public'
    ]

SPOTIFY_AUTHORIZATION_SCOPE = ' '.join(auth_scopes)

this_dir = os.path.dirname(__file__)

with open(os.path.join(this_dir, 'genre_seeds.txt')) as f:
    SPOTIFY_GENRE_SEEDS = f.read().splitlines()