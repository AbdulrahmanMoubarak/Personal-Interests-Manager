import sqlite3
import json
from random import randrange
from concurrent.futures.thread import ThreadPoolExecutor
from InterestsRecommender.MoviesRecommender import MovieRecommender
from tmdbv3api import TMDb
from TMDBCredentials import TmdbCredentials
from ProjectModels import MovieModel
from ProjectModels import MediaItemPartialModel
from ProjectModels import SectionModel
from datetime import datetime, date
from tmdbv3api import Trending
from tmdbv3api import Movie
from tmdbv3api import Discover
from tmdbv3api import Collection
from tmdbv3api import Company
from random import shuffle
import asyncio

tmdb = TMDb()
tmdb.language = 'en'
tmdb.debug = True
tmdb.api_key = TmdbCredentials.API_KEY


class MoviesManager:
    def __connectToDB(self):
        con = sqlite3.connect(
            "D:/FCIS SWE 2021/Graduation Project/Project source code/Dataset Migration/pim_database.db")
        return con

    async def getHomePageMovies(self, userId):
        randomYear = randrange(2000, int(date.today().year))
        randomGenre = self.__getRandomGenre()

        secList = []

        with ThreadPoolExecutor(max_workers=8) as executor:

            localCollabRecommend = executor.submit(self.__getCollabLocalRecommendation,userId)
            localContentRecommend = executor.submit(self.__getContentLocalRecommendation, userId)
            tmdbTrendingDay = executor.submit(self.__getDayTrendingMovies)
            tmdbTrendingWeek = executor.submit(self.__getWeekTrendingMovies)
            tmdbDiscoverYear = executor.submit(self.__getMoviesFromTmdbDiscover, randomYear)
            tmdbDiscoverGenre = executor.submit(self.__getRandomGenreMoviesFromTmdb, randomGenre[0])
            tmdbUpcoming = executor.submit(self.__getUpcomingMovies)
            tmdbTopRated = executor.submit(self.__getRandomTopRatedMovies)

            trendinDay = SectionModel("Trending Today", tmdbTrendingDay.result())
            secList.append(trendinDay)
            trendinWeek = SectionModel("Trending This Week", tmdbTrendingWeek.result())
            secList.append(trendinWeek)
            upcomingMovies = SectionModel("Upcoming Movies", tmdbUpcoming.result())
            secList.append(upcomingMovies)
            genreMovies = SectionModel("Popular " + randomGenre[1] + " Movies", tmdbDiscoverGenre.result())
            secList.append(genreMovies)
            yearMovies = SectionModel("Popular Movies in " + str(randomYear), tmdbDiscoverYear.result())
            secList.append(yearMovies)
            topMovies = SectionModel("Top Rated Movies", tmdbTopRated.result())
            secList.append(topMovies)

            localCollabRes = localCollabRecommend.result()
            localCollabRec = SectionModel("People Like You Also Viewed", localCollabRes)

            localContentRes = localContentRecommend.result()
            localContentRec = SectionModel("Hobbitor Recommendation", localContentRes)

            if (len(localContentRes) > 5):
                secList.append(localContentRec)

            if (len(localCollabRes) > 5):
                secList.append(localCollabRec)

            return json.dumps(secList, default=SectionModel.to_dict)

    def findMovieCast(self, movieId):
        tmdb_movie = Movie()
        response = tmdb_movie.credits(movieId)
        cast = self.__extractCastFromResponse(response)
        return json.dumps(cast, default=MediaItemPartialModel.to_dict)

    def getMovieBasedRecommendation(self, movieId, userId):
        sec_list = []
        tmdb_movie = Movie()
        tmdb_collection = Collection()
        tmdb_company = Company()

        with ThreadPoolExecutor(max_workers=2) as executor:
            peopleRecommendation = executor.submit(self.__getMovieBasedLocalCollabRecommendation, movieId, userId)
            contentRecommendation = executor.submit(self.__getMovieBasedLocalContentRecommendation, movieId)

        mDetails = tmdb_movie.details(movieId)
        try:
            movieCollection = mDetails['belongs_to_collection']['id']
        except:
            movieCollection = None

        if movieCollection != None:
            collectionResponse = self.__extractMoviesFromResponse(tmdb_collection.details(movieCollection)['parts'])
            sameCollection = SectionModel("Movies From The Collection", collectionResponse)
            sec_list.append(sameCollection)

        similarMoviesResponse = self.__extractMoviesFromResponse(tmdb_movie.similar(movieId, page=randrange(1, 10)))
        similarMovies = SectionModel("Similar Movies", similarMoviesResponse)
        sec_list.append(similarMovies)

        if (len(mDetails['genres']) > 1):
            randNum = randrange(0, len(mDetails['genres']) - 1)
        else:
            randNum = 0
        movieGenre = mDetails['genres'][randNum]
        similarMovieGenreResponse = self.__getRandomGenreMoviesFromTmdb(movieGenre['id'])
        similarByGenre = SectionModel("Popular " + movieGenre['name'] + " Movies", similarMovieGenreResponse)
        sec_list.append(similarByGenre)

        if len(mDetails['production_companies']) > 1:
            movieCompany = mDetails['production_companies'][randrange(0, len(mDetails['production_companies']) - 1)]
        else:
            movieCompany = mDetails['production_companies'][0]

        similarCompanyResponse = self.__extractMoviesFromResponse(tmdb_company.movies(movieCompany['id']))
        similarByComp = SectionModel("Also From " + movieCompany['name'], similarCompanyResponse)
        sec_list.append(similarByComp)

        collabRes = peopleRecommendation.result()
        if len(collabRes) > 0:
            peopleAlsoSec = SectionModel("People Who Liked This Also Liked", collabRes)
            sec_list.append(peopleAlsoSec)

        contentRes = contentRecommendation.result()
        if (len(contentRes) > 0):
            hobbitorRecSec = SectionModel("Recommended By Hobbitor", contentRes)
            sec_list.append(hobbitorRecSec)

        return json.dumps(sec_list, default=SectionModel.to_dict)

    def addMovieRatingToDb(self, movieId, userId, rating):
        con = self.__connectToDB()
        cur = con.cursor()

        res = cur.execute('''SELECT * FROM movies_metadata WHERE movie_id = (?)''', [movieId]).fetchall()

        if len(res) == 0:
            mDetails = self.__processTMDBMovieDetails(Movie().details(movieId))
            cur.execute('''INSERT INTO movies_metadata VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', mDetails)

        try:
            cur.execute('''INSERT INTO movie_rating VALUES (?,?,?)''', [userId, movieId, rating])
            con.commit()
            con.close()
            return True
        except:
            con.close()
            return False

    def __getCollabLocalRecommendation(self, userId):
        conn = self.__connectToDB()
        cur = conn.cursor()
        idList = MovieRecommender().CollabWithUserId(userId, self.__connectToDB())
        mList = []
        for mId in idList:
            rec = cur.execute(''' SELECT movie_id,title,poster FROM movies_metadata WHERE movie_id = (?)''',
                              [mId]).fetchone()
            mList.append(MediaItemPartialModel.to_dict(MediaItemPartialModel(mId, rec[1], rec[2], "movie")))
        return mList

    def __getContentLocalRecommendation(self, userId):
        con = self.__connectToDB()
        cur = con.cursor()
        idList = MovieRecommender().ContentWithUserId(userId, con, 3)
        mList = []
        for mId in idList:
            rec = cur.execute(''' SELECT movie_id,title,poster FROM movies_metadata WHERE movie_id = (?)''',
                              [mId]).fetchone()
            mList.append(MediaItemPartialModel.to_dict(MediaItemPartialModel(mId, rec[1], rec[2], "movie")))
        return mList

    def __getMovieBasedLocalCollabRecommendation(self, movieId, userId):
        con = self.__connectToDB()
        cur = con.cursor()
        idList = MovieRecommender().CollabWithMovieId(userId, movieId, con)
        mList = []
        for mId in idList:
            rec = cur.execute(''' SELECT movie_id,title,poster FROM movies_metadata WHERE movie_id = (?)''',
                              [mId]).fetchone()
            mList.append(MediaItemPartialModel.to_dict(MediaItemPartialModel(mId, rec[1], rec[2], "movie")))
        return mList

    def __getMovieBasedLocalContentRecommendation(self, movieId):
        con = self.__connectToDB()
        cur = con.cursor()
        idList = MovieRecommender().ContentWithMovieId(movieId, con, 6)
        mList = []
        for mId in idList:
            rec = cur.execute(''' SELECT movie_id,title,poster FROM movies_metadata WHERE movie_id = (?)''',
                              [mId]).fetchone()
            mList.append(MediaItemPartialModel.to_dict(MediaItemPartialModel(mId, rec[1], rec[2], "movie")))
        return mList

    def __extractMoviesFromResponse(self, response):
        mList = []
        for movie in response:
            mId = movie['id']
            mTitle = movie['title']
            mPoster = movie['poster_path']
            mList.append(MediaItemPartialModel.to_dict(MediaItemPartialModel(mId, mTitle, mPoster, "movie")))
        return mList

    def __extractCastFromResponse(self, response):
        cList = []
        i = 0
        for castMember in response['cast']:
            cImage = castMember['profile_path']
            cName = castMember['name']
            cChar = castMember['character']
            cList.append(MediaItemPartialModel(cChar, cName, cImage, type="cast_member"))
            i += 1
        return cList

    def findMovieByGenre(self, genre):
        mList = []
        movieList = self.__findSimilarMoviesInDbByGenre("%" + genre + "%")
        for movie in movieList:
            mId = movie[0]
            mTitle = movie[1]
            mPoster = movie[2]
            mList.append(MediaItemPartialModel.to_dict(MediaItemPartialModel(mId, mTitle, mPoster, "movie")))

        tmdb_movieList = self.__tmdbSearchForMovie(genre)
        mySearchSec = SectionModel("Search Results", mList)
        tmdbSearchSec = SectionModel("Results From TMDB", tmdb_movieList)

        secList = [mySearchSec, tmdbSearchSec]

        return json.dumps(secList, default=SectionModel.to_dict)

    def findMovieByName(self, name):
        tmdb_movieList = self.__tmdbSearchForMovie(name)
        return json.dumps(tmdb_movieList, default=MediaItemPartialModel.to_dict)

    def findMovieById(self, id, userId):
        id = int(id)

        con = self.__connectToDB()
        cur = con.cursor()
        cur.execute('''SELECT * FROM movies_metadata WHERE movie_id = (?)''', [id])
        result = cur.fetchall()

        try:
            user_rating = cur.execute(''' SELECT rating FROM movie_rating WHERE user_id = (?) AND movie_id = (?)''',
                                      [userId, id]).fetchall()[0][0]
        except:
            user_rating = -1.0
        con.close()
        if len(result) == 0:
            return json.dumps(self.__tmdbGetMovieById(id, user_rating), default=MovieModel.to_dict)
        else:
            mMovie = MovieModel(result[0])
            mMovie.user_rating = user_rating
            return json.dumps(mMovie, default=MovieModel.to_dict)

    def __findSimilarMoviesInDbByName(self, movie):
        con = self.__connectToDB()
        cur = con.cursor()
        cur.execute(
            ''' SELECT movie_id, title, poster FROM movies_metadata WHERE title like (?) ORDER BY popularity DESC LIMIT 20 OFFSET 0''',
            [movie])
        result = cur.fetchall()
        con.close()
        return result

    def __findSimilarMoviesInDbByGenre(self, genres):
        con = self.__connectToDB()
        cur = con.cursor()
        cur.execute(
            ''' SELECT movie_id, title, poster FROM movies_metadata WHERE genres like (?) ORDER BY popularity DESC LIMIT 20 OFFSET 0''',
            [genres])
        result = cur.fetchall()
        con.close()
        return result

    def __tmdbSearchForMovie(self, query=""):
        tmdb_movies = Movie()
        results = tmdb_movies.search(query)
        mList = []
        for movie in results:
            mId = movie['id']
            mTitle = movie['title']
            mPoster = movie['poster_path']
            mList.append(MediaItemPartialModel.to_dict(MediaItemPartialModel(mId, mTitle, mPoster, "movie")))
        return mList

    def __tmdbGetMovieById(self, mId, user_rating):
        try:
            mDetails = Movie().details(mId)
        except:
            return
        mMovie = MovieModel(self.__processTMDBMovieDetails(mDetails))
        mMovie.user_rating = user_rating
        return mMovie

    def __getDayTrendingMovies(self):
        trending = Trending()
        tmdb_trendingDay = trending.all_day(1)
        mList = []
        for movie in tmdb_trendingDay:
            try:
                mId = movie['id']
                mTitle = movie['title']
                mPoster = movie['poster_path']
            except:
                continue
            mList.append(MediaItemPartialModel.to_dict(MediaItemPartialModel(mId, mTitle, mPoster, "movie")))
        return mList

    def __getUpcomingMovies(self):
        tmdb_movies = Movie()
        results = tmdb_movies.upcoming()
        mList = []
        for movie in results:
            mId = movie['id']
            mTitle = movie['title']
            mPoster = movie['poster_path']
            mList.append(MediaItemPartialModel.to_dict(MediaItemPartialModel(mId, mTitle, mPoster, "movie")))
        return mList

    def __getRandomTopRatedMovies(self):
        tmdb_movies = Movie()
        results = tmdb_movies.top_rated(randrange(1, 10))
        mList = []
        for movie in results:
            mId = movie['id']
            mTitle = movie['title']
            mPoster = movie['poster_path']
            mList.append(MediaItemPartialModel.to_dict(MediaItemPartialModel(mId, mTitle, mPoster, "movie")))
        return mList

    def __getWeekTrendingMovies(self):
        trending = Trending()
        tmdb_trendingDay = trending.all_week(1)
        mList = []
        for movie in tmdb_trendingDay:
            try:
                mId = movie['id']
                mTitle = movie['title']
                mPoster = movie['poster_path']
            except:
                continue
            mList.append(MediaItemPartialModel.to_dict(MediaItemPartialModel(mId, mTitle, mPoster, "movie")))
        return mList

    def __getMoviesFromTmdbDiscover(self, year):
        tmdb_discover = Discover()
        res = tmdb_discover.discover_movies(
            {"primary_release_year": str(year), "sort_by": "popularity.desc", "language": "en-US",
             "page": randrange(1, 10)})
        mList = []
        for movie in res:
            try:
                mId = movie['id']
                mTitle = movie['title']
                mPoster = movie['poster_path']
            except:
                continue
            mList.append(MediaItemPartialModel.to_dict(MediaItemPartialModel(mId, mTitle, mPoster, "movie")))
        return mList

    def __getRandomGenre(self):
        con = self.__connectToDB()
        cur = con.cursor()
        cur.execute(''' SELECT genre_id, genre_name FROM movie_genres''')
        genres = cur.fetchall()
        randIndex = randrange(0, len(genres) - 1)
        con.close()
        return genres[randIndex]

    def __getRandomGenreMoviesFromTmdb(self, genre):
        tmdb_discover = Discover()
        res = tmdb_discover.discover_movies(
            {"with_genres": str(genre), "sort_by": "popularity.desc", "language": "en-US", "page": randrange(1, 10)})
        mList = []
        for movie in res:
            try:
                mId = movie['id']
                mTitle = movie['title']
                mPoster = movie['poster_path']
            except:
                continue
            mList.append(MediaItemPartialModel.to_dict(MediaItemPartialModel(mId, mTitle, mPoster, "movie")))
        return mList

    def __processTMDBMovieDetails(self, mDetails):
        mId = mDetails['id']
        mAdult = mDetails['adult']
        mTitle = mDetails['title']
        mOverview = mDetails['overview']
        mBackground = mDetails['backdrop_path']
        mCollection = mDetails['belongs_to_collection']
        if mCollection != None:
            mCollection = mCollection['name']
        mGenres = ""
        for gen in mDetails['genres']:
            mGenres += gen['name'] + "|"
        mLanguage = mDetails['original_language']
        mPopularity = float(mDetails['popularity'])
        mPoster = mDetails['poster_path']
        try:
            mYear = int(str(mDetails['release_date']).split('-')[0])
        except:
            mYear = 0
        try:
            mDate = mDetails['release_date']
        except:
            mDate = "Unknown"
        mStatus = mDetails['status']
        mTrailer = ""
        try:
            for trailer in mDetails['trailers']['youtube']:
                if trailer['type'] == 'Trailer':
                    mTrailer = trailer['source']
                    if trailer['name'] == 'Official IMAX® Trailer':
                        break
        except:
            mTrailer = "None"
        mVoteAverage = float(mDetails['vote_average'])
        mVoteCount = int(mDetails['vote_count'])
        mTagline = mDetails['tagline']
        mImdbId = mDetails['imdb_id']
        mProductionCompanies = ""
        for comp in mDetails['production_companies']:
            mProductionCompanies += comp['name'] + "|"
        return [mAdult, mCollection, mGenres, mId, mLanguage, mOverview, mPopularity, mPoster, mProductionCompanies,
                mDate,
                mStatus, mTagline, mTitle, mVoteAverage, mVoteCount, mImdbId,
                mYear,
                mTrailer,
                mBackground
                ]
