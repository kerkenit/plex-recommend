import operator
import sys
import time
import locale
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

ap.add_argument('--exclude_collection', action='append', metavar="Christmas, Holiday",
                help="Exclude a collection from your library. Can be added multiple times")
ap.add_argument('--include_collection', action='append', metavar="James Bond",
                help="Include a collection from your library. Can be added multiple times. (Not Strict)")
ap.add_argument('--exclude_genre', action='append', metavar="Horror",
                help="Exclude a genre from your library. Can be added multiple times")
args = vars(ap.parse_args())


try:
    locale.setlocale(locale.LC_TIME, str(locale.getlocale()[0]) + ".UTF-8")
except:
    locale.setlocale(locale.LC_TIME, "en_US.UTF-8")
    pass

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
audiance_score = {}
collections_score = {}

if args['exclude_genre'] is not None:
    for genre in args['exclude_genre']:
        if not genre in collections_score:
            genre_score[genre] = float(-500)
        else:
            genre_score[genre] += float(-500)

if args['exclude_collection'] is not None:
    for collection in args['exclude_collection']:
        if not collection in collections_score:
            collections_score[collection] = float(-25)
        else:
            collections_score[collection] += float(-25)

if args['include_collection'] is not None:
    for collection in args['include_collection']:
        if not collection in collections_score:
            collections_score[collection] = float(25)
        else:
            collections_score[collection] += float(25)


def fetch_plex_api(path="", method="GET", plextv=False, **kwargs):
    url = "https://plex.tv" if plextv else PLEX_URL.rstrip("/")
    headers = {"X-Plex-Token": PLEX_TOKEN, "Accept": "application/json"}
    params = {}
    if kwargs:
        params.update(kwargs)

    try:
        if method.upper() == "GET":
            r = requests.get(url + path, headers=headers, params=params, verify=False)
        elif method.upper() == "POST":
            r = requests.post(url + path, headers=headers, params=params, verify=False)
        elif method.upper() == "PUT":
            r = requests.put(url + path, headers=headers, params=params, verify=False)
        elif method.upper() == "DELETE":
            r = requests.delete(url + path, headers=headers, params=params, verify=False)
        else:
            print("Invalid request method provided: {method}".format(method=method))
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
                except Exception as e:
                    print("Delete playlist: {err}".format(err=e))
                    pass

        for section, shows in result.items():
            if section in EXCLUDE_SECTIONS:
                continue

            playlist_title = PLAYLIST_NAME + " " + section
            media = []
            for s in shows:
                try:
                    media.append(get_first_episode(s))
                except Exception as e:
                    print("get_first_episode: {err}".format(err=e))
                    pass

            if len(media) > 0:
                try:
                    playlist = plex.createPlaylist(playlist_title, media)
                    playlist.edit(playlist_title, time.strftime("%A %d %b %Y %H:%M:%S"))
                except Exception as e:
                    print("createPlaylist: {err}".format(err=e))
                    pass


def get_first_episode(show, season_num=1):
    try:
        return show.episode(season=season_num, episode=1) if isinstance(show, Show) else show
    except Exception as e:
        return show
        pass


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
    watched_shows = [s for s in shows if s.isWatched or s.viewCount > 0 or (hasattr(s, 'userRating') and s.userRating is not None and s.userRating > 0)]

    for show in watched_shows:
        try:
            rating = show.userRating if show.userRating is not None else show.rating if show.rating is not None else SHOW_DEFAULT_RATING
        except:
            rating = show.rating if show.rating is not None else SHOW_DEFAULT_RATING


        iAudiance = 18
        if hasattr(show, 'contentRating'):
            audiance = get_audiance_name(show.contentRating)

            try:
                iAudiance = int(audiance)
            except:
                iAudiance = 18
            rating = rating * (18 / iAudiance)

            if not audiance in audiance_score:
                audiance_score[audiance] = rating
            else:
                audiance_score[audiance] += rating

        show_multiplier = rating / 10 if SHOW_MULTIPLIER else 1
        try:
            for index, cast in enumerate(show.actors):
                if not cast.tag in cast_score:
                    cast_score[cast.tag] = calculate_range_score(index, CAST_RANGE) * show_multiplier
                else:
                    cast_score[cast.tag] += calculate_range_score(index, CAST_RANGE) * show_multiplier
        except AttributeError:
            pass
        except Exception as e:
            print("cast_score: {err}".format(err=e))
            pass

        try:
             if show.writers is not None :
                for index, writer in enumerate(show.writers):
                    if not writer in writers_score:
                        writers_score[writer] = calculate_range_score(index, CAST_RANGE) * show_multiplier
                    else:
                        writers_score[writer] += calculate_range_score(index, CAST_RANGE) * show_multiplier
        except AttributeError:
            pass
        except Exception as e:
            print("writers_score: {err}".format(err=e))
            pass

        try:
             if show.directors is not None :
                for index, director in enumerate(show.directors):
                    if not director in directors_score:
                        directors_score[director] = calculate_range_score(index, 3, in_range_diff=False, base_score=10, out_range_score=3) * show_multiplier
                    else:
                        directors_score[director] += calculate_range_score(index, 3, in_range_diff=False, base_score=10, out_range_score=3) * show_multiplier
        except AttributeError:
            pass
        except Exception as e:
            print("directors_score: {err}".format(err=e))
            pass

        try:
             if show.countries is not None :
                for index, country in enumerate(show.countries):
                    if not country in countries_score:
                        countries_score[country] = calculate_range_score(index, 3, in_range_diff=True, base_score=2, out_range_score=1) * show_multiplier
                    else:
                        countries_score[country] += calculate_range_score(index, 3, in_range_diff=True, base_score=2, out_range_score=1) * show_multiplier
        except AttributeError:
            pass
        except Exception as e:
            print("countries_score: {err}".format(err=e))

        try:
            if show.roles is not None :
                for index, role in enumerate(show.roles):
                    if not role in roles_score:
                        roles_score[role] = calculate_range_score(index, CAST_RANGE, in_range_diff=True, base_score=5, out_range_score=1) * show_multiplier
                    else:
                        roles_score[role] += calculate_range_score(index, CAST_RANGE, in_range_diff=True, base_score=5, out_range_score=1) * show_multiplier
        except AttributeError:
            pass
        except Exception as e:
            print("roles_score: {err}".format(err=e))



        try:
             if show.genres is not None :
                for index, genre in enumerate(show.genres):
                    if not genre.tag in genre_score:
                        genre_score[genre.tag] = calculate_range_score(index, GENRE_RANGE, in_range_diff=False, base_score=20, out_range_score=1) * show_multiplier
                    else:
                        genre_score[genre.tag] += calculate_range_score(index, GENRE_RANGE, in_range_diff=False, base_score=20, out_range_score=1) * show_multiplier
        except AttributeError:
            pass
        except Exception as e:
            print("genre_score: {err}".format(err=e))

        try:
            if show.studio is not None :
                for index, studio in enumerate(show.studio):
                    studio_score[studio] = calculate_range_score(index, 2, in_range_diff=True, base_score=3, out_range_score=1) * show_multiplier
        except AttributeError:
            pass
        except Exception as e:
            print("studio_score: {err}".format(err=e))

def filter_show(section):
    shows = section.all()
    unwatch_shows = [s for s in shows if not s.isWatched and s.viewCount <= 0]

    show_score = {}
    for show in unwatch_shows:
        #try:
        #    rating = show.rating if show.rating is not None else show.userRating if show.userRating is not None else SHOW_DEFAULT_RATING
        #except:
        rating = show.rating if show.rating is not None else SHOW_DEFAULT_RATING

        show_multiplier = rating / 10 if SHOW_MULTIPLIER else 1
        show_score[show] = 0
        try:
            show_score[show] += studio_score.get(show.studio, 0)
        except Exception as e:
            print("show_score-studio_score: {err}".format(err=e))

        for cast in [a for a in show.actors if a.tag in cast_score]:
            show_score[show] += cast_score[cast.tag]

        for genre in [g for g in show.genres if g.tag in genre_score]:
            show_score[show] += genre_score[genre.tag]

        try:
            for writer in [g for g in show.writers if g in writers_score]:
                show_score[show] += writers_score[writer]
        except Exception as e:
            print("show_score-writers_score: {err}".format(err=e))

        try:
            for director in [g for g in show.directors if g in directors_score]:
                show_score[show] += directors_score[director]
        except Exception as e:
            print("show_score-directors_score: {err}".format(err=e))

        try:
            for country in [g for g in show.countries if g in countries_score]:
                show_score[show] += countries_score[country]
        except Exception as e:
            print("show_score-countries_score: {err}".format(err=e))

        try:
            for role in [a for a in show.roles if a in roles_score]:
                show_score[show] += roles_score[role]
        except Exception as e:
            print("show_score-roles_score: {err}".format(err=e))


        if hasattr(show, 'contentRating'):
            audiance = get_audiance_name(show.contentRating)


            if audiance in audiance_score:
                iAudiance = 18
                try:
                    iAudiance = int(audiance)
                except Exception as e:
                    print("iAudiance: {err}".format(err=e))
                if iAudiance < 18:
                    show_score[show] += audiance_score[audiance]


        try:
            for index, collection in enumerate(collections_score):
                for a in show.collections:
                    if str(a).find(collection) != -1:
                        show_score[show] += collections_score.get(collection, 0)
        except Exception as e:
            print("collections_score: {err}".format(err=e))

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


def get_audiance_name(rating):
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
    rating = rating.replace("TV-Y", "")
    rating = rating.replace("NL/MG6", "6")
    rating = rating.replace("NL/ALL", "4")
    rating = rating.replace("NL/AL", "4")
    rating = rating.replace("NL/6", "6")
    rating = rating.replace("NL/7+", "8")
    rating = rating.replace("NL/7", "7")
    rating = rating.replace("NL/8", "8")
    rating = rating.replace("NL/9", "9")
    rating = rating.replace("NL/10", "12")
    rating = rating.replace("NL/11", "12")
    rating = rating.replace("NL/12", "12")
    rating = rating.replace("NL/14", "12")
    rating = rating.replace("NL/16+", "18")
    rating = rating.replace("NL/16", "16")
    rating = rating.replace("NL/18", "18")
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

    rating = rating.replace("ALL", "2")
    rating = rating.replace("AL", "2")
    rating = rating.replace("3", "2")
    rating = rating.replace("4", "2")
    rating = rating.replace("5", "2")
    rating = rating.replace("7", "6")
    rating = rating.replace("8", "6")
    rating = rating.replace("9", "9")
    rating = rating.replace("10", "9")
    rating = rating.replace("11", "9")
    rating = rating.replace("13", "12")
    rating = rating.replace("14", "12")
    rating = rating.replace("15", "12")
    rating = rating.replace("17", "18")
    rating = rating.replace("16", "18")

    return rating


if __name__ == "__main__":
    main()
