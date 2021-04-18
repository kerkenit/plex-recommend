import operator
import sys
import argparse
import requests
import urllib3
import xmltodict
from plexapi.library import ShowSection, MovieSection
from plexapi.server import PlexServer
from plexapi.video import Show

# Construct the argument parser
ap = argparse.ArgumentParser(
    description='Creates a playlist of Plex Recommendations', allow_abbrev=False)
ap.add_argument('--version', action='version', version='%(prog)s 2.0')

# Add the arguments to the parser
ap.add_argument("--plextoken", required=True,
                help="Plex token. See https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/ how to get the token")
ap.add_argument("--plexurl", required=False,
                help="Plex URL. Leave empty to use localhost")
ap.add_argument("--cast", required=False, type=int, default=5,
                metavar='{5-10}', choices=range(5, 11), help="Range persons of the cast. Default value 5")
ap.add_argument("--genre", required=False, type=int, default=3,
                metavar='{1-10}', choices=range(1, 11), help="Range of genres. Default value 3")
ap.add_argument("--rating", required=False, type=float, default=2,
                metavar='{0-5}', choices=range(0, 6), help="Default rating when empty. Default value: 2")
ap.add_argument("--muliplier", required=False, type=bool, default=True,
                metavar='True', help="Mulitplier Posible values: True or False")
ap.add_argument("--size", required=False, type=int, default=10,
                metavar='{10,25,50,100}', choices=[10, 25, 50, 100], help="Length of playlist, Default 10")
ap.add_argument("--name", required=False, type=str, default='"Recommend for"',
                metavar='Default: "Recommend for"', help="Playlist name prefix")
ap.add_argument('--exclude_section', action='append', metavar="Home video's, Music Video's",
                help="Exclude a section from your library. Can be added multiple times")
args = vars(ap.parse_args())

#Plex Parameters
PLEX_URL = args['plexurl']
PLEX_TOKEN = args['plextoken']

# Analysis Parameters
CAST_RANGE = args['cast']
SHOW_MULTIPLIER = args['muliplier']
SHOW_DEFAULT_RATING = args['rating']
GENRE_RANGE = args['genre']
PLAYLIST_SIZE = args['size']
PLAYLIST_NAME = args['name']
EXCLUDE_SECTIONS = args['exclude_section']

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

cast_score = {}
genre_score = {}
studio_score = {}
writers_score = {}
directors_score = {}
countries_score = {}
roles_score = {}

def fetch_plex_api(path="", method="GET", plextv=False, **kwargs):
    url = "https://plex.tv" if plextv else PLEX_URL.rstrip("/")
    headers = {"X-Plex-Token": PLEX_TOKEN, "Accept": "application/json"}
    params = {}
    if kwargs:
        params.update(kwargs)

    try:
        if method.upper() == "GET":
            r = requests.get(url + path, headers=headers,
                             params=params, verify=False)
        elif method.upper() == "POST":
            r = requests.post(url + path, headers=headers,
                              params=params, verify=False)
        elif method.upper() == "PUT":
            r = requests.put(url + path, headers=headers,
                             params=params, verify=False)
        elif method.upper() == "DELETE":
            r = requests.delete(url + path, headers=headers,
                                params=params, verify=False)
        else:
            print("Invalid request method provided: {method}".format(
                method=method))
            return

        if r and len(r.content):
            if "application/json" in r.headers["Content-Type"]:
                return r.json()
            elif "application/xml" in r.headers["Content-Type"]:
                return xmltodict.parse(r.content)
            else:
                return r.content
        else:
            return r.content

    except Exception as e:
        print("Error fetching from Plex API: {err}".format(err=e))


def get_user_tokens(server_id):
    api_users = fetch_plex_api("/api/users", plextv=True)
    api_shared_servers = fetch_plex_api(
        "/api/servers/{server_id}/shared_servers".format(server_id=server_id), plextv=True)
    user_ids = {user["@id"]: user.get("@username", user.get("@title"))
                for user in api_users["MediaContainer"]["User"]}
    users = {user_ids[user["@userID"]]: user["@accessToken"]
             for user in api_shared_servers["MediaContainer"]["SharedServer"]}
    return users


def main():
    plex_server = PlexServer(PLEX_URL, PLEX_TOKEN)
    users_plex = [plex_server]
    plex_users = get_user_tokens(plex_server.machineIdentifier)
    users_plex.extend([PlexServer(PLEX_URL, u) for n, u in plex_users.items()])

    for plex in users_plex:
        result = analysis(plex)
        for playlist in plex.playlists():
            if playlist.title.startswith(PLAYLIST_NAME + " "):
                try:
                   playlist.delete()
                except:
                   pass

        for section, shows in result.items():
            if section in EXCLUDE_SECTIONS:
               continue

            playlist_title = PLAYLIST_NAME + " " + section
            media = []
            for s in shows:
                try:
                    media.append(get_first_episode(s))
                except:
                    pass

            if len(media) > 0:
               try:
                  plex.createPlaylist(playlist_title, media)
               except:
                  pass


def get_first_episode(show, season_num=1):
    return show.episode(season=season_num, episode=1) if isinstance(show, Show) else show


def analysis(plex):
    result = {}
    for section in plex.library.sections():
        if not isinstance(section, ShowSection) and not isinstance(section, MovieSection):
            continue
        analysis_show(section)

    for section in plex.library.sections():
        if not isinstance(section, ShowSection) and not isinstance(section, MovieSection):
            continue
        result[section.title] = filter_show(section)
    return result


def analysis_show(section):
    shows = section.all()
    watched_shows = [s for s in shows if s.isWatched or s.viewCount > 0 or (
        hasattr(s, 'userRating') and s.userRating is not None and s.userRating > 0)]

    for show in watched_shows:
        try:
            rating = show.userRating if show.userRating is not None else show.rating if show.rating is not None else SHOW_DEFAULT_RATING
        except:
            rating = show.rating if show.rating is not None else SHOW_DEFAULT_RATING

        show_multiplier = rating / 10 if SHOW_MULTIPLIER else 1
        for index, cast in enumerate(show.actors):
            cast_score[cast.tag] = calculate_range_score(
                index, CAST_RANGE) * show_multiplier

        try:
            for index, writer in enumerate(show.writers):
                writers_score[writer] = calculate_range_score(
                    index, CAST_RANGE) * (show_multiplier / 3)
        except:
            pass

        try:
            for index, director in enumerate(show.directors):
                directors_score[director] = calculate_range_score(
                    index, 3, in_range_diff=False, base_score=15, out_range_score=3) * (show_multiplier / 2)
        except:
            pass

        try:
            for index, country in enumerate(show.countries):
                countries_score[country] = calculate_range_score(
                    index, 3, in_range_diff=True, base_score=5, out_range_score=1) * (show_multiplier / 2)
        except:
            pass

        try:
            for index, role in enumerate(show.roles):
                roles_score[country] = calculate_range_score(
                    index, CAST_RANGE, in_range_diff=True, base_score=10, out_range_score=1) * show_multiplier
        except:
            pass

        if hasattr(show, 'contentRating'):
            audience = get_audience_name(show.contentRating)
            if not audience in audience_score:
                audience_score[audience] = show_multiplier * show_multiplier
            else:
                audience_score[audience] += show_multiplier * show_multiplier

        for index, genre in enumerate(show.genres):
            genre_score[genre.tag] = calculate_range_score(
                index, GENRE_RANGE, in_range_diff=False, base_score=20, out_range_score=1) * show_multiplier

        try:
            for index, studio in enumerate(show.studio):
                studio_score[studio] = calculate_range_score(
                    index, 2, in_range_diff=True, base_score=5, out_range_score=1) * (show_multiplier / 3)
        except:
            pass

def filter_show(section):
    shows = section.all()
    unwatch_shows = [s for s in shows if not s.isWatched and s.viewCount <= 0]

    show_score = {}
    for show in unwatch_shows:
        try:
            rating = show.rating if show.rating is not None else show.userRating if show.userRating is not None else SHOW_DEFAULT_RATING
        except:
            rating = show.rating if show.rating is not None else SHOW_DEFAULT_RATING

        show_multiplier = rating / 10 if SHOW_MULTIPLIER else 1
        show_score[show] = 0
        try:
            show_score[show] += studio_score.get(show.studio, 0)
        except:
            pass

        for cast in [a for a in show.actors if a.tag in cast_score]:
            show_score[show] += cast_score[cast.tag]

        for genre in [g for g in show.genres if g.tag in genre_score]:
            show_score[show] += genre_score[genre.tag]

        try:
            for writer in [g for g in show.writers if g in writers_score]:
                show_score[show] += writers_score[writer]
        except:
            pass

        try:
            for director in [g for g in show.directors if g in directors_score]:
                show_score[show] += directors_score[director]
        except:
            pass

        try:
            for country in [g for g in show.countries if g in countries_score]:
                show_score[show] += countries_score[country]
        except:
            pass

        try:
            for role in [a for a in show.roles if a in roles_score]:
                show_score[show] += roles_score[role]
        except:
            pass

        if hasattr(show, 'contentRating'):
            audience = get_audience_name(show.contentRating)
            if audience in audience_score:
                show_score[show] += audience_score[audience]

        try:
            for index, collection in enumerate(collections_score):
                for a in show.collections:
                    if str(a).find(collection) != -1:
                        show_score[show] += collections_score.get(
                            collection, 0)
        except:
            pass

        show_score[show] *= show_multiplier
    recommend = sorted(show_score.items(), key=operator.itemgetter(1), reverse=True)[:PLAYLIST_SIZE]
    return [r[0] for r in recommend]


def calculate_range_score(position, in_range, in_range_diff=True, in_range_diff_multiplier=1.0, base_score=0.1, out_range_score=0.1):
    if in_range <= 0:
        return base_score

    if position >= in_range:
        return base_score + out_range_score

    if in_range_diff:
        return base_score + (in_range - position) * in_range_diff_multiplier
    else:
        return base_score + in_range


def get_audience_name(rating):
    if rating is not None:
        rating = str(rating).upper()
    else:
        rating = "UNRATED"

    rating = rating.replace("NONE", "UNRATED")
    rating = rating.replace("NL/NR", "UNRATED")
    rating = rating.replace("NL/AL", "ALL")
    rating = rating.replace("NOT RATED", "UNRATED")
    rating = rating.replace("TV-PG", "13")
    rating = rating.replace("PG-13", "13")
    rating = rating.replace("TV-G", "13")
    rating = rating.replace("TV-MA", "17")
    rating = rating.replace("NL/MG6", "6")
    rating = rating.replace("NL/", "")
    rating = rating.replace("TV-", "")
    rating = rating.replace("PG-", "")
    rating = rating.replace("PG", "13")
    rating = rating.replace("12-12", "12")

    rating = rating.replace("UNRATED", "12")
    rating = rating.replace("NR", "UNRATED")

    rating = rating.replace("UNRATED", "12")
    rating = rating.replace("G", "ALL")
    rating = rating.replace("R", "18")
    rating = rating.replace("Y", "6")

    rating = rating.replace("ALL", "6")
    rating = rating.replace("AL", "6")
    rating = rating.replace("13", "12")
    rating = rating.replace("14", "12")
    rating = rating.replace("17", "18")

    return rating


if __name__ == "__main__":
    main()
