"""Internal functions for sending http requests or retrieving cached
data.

License:
    GNU General Public License v3.0

Version:
    0.0.1

Copyright 2017, Stacy Irwin
"""
import datetime
import json
import os
import os.path
import pickle
import urllib.request
import urllib.error
import base64
import warnings

import pandas
from pandas.io import json as pj


def build_url(session, command, http_args=None):
    """
    Returns a FIRST API compliant URL.

    Args:
        session: An instance of fapy.Session
        command: A string specifying what type of data should be
            returned by the FIRST API, such as "teams", "schedule",
            "scores", "status", etc.
        http_args: A dictionary containing the parameters that will be
            sent to the FIRST API as GET parameters (i.e., parameters
            that follow the '?' in the URL). The dictionary key is the
            name of the GET parameter and the dictionary value is the
            GET parameter value.

    Returns: A string containing a URL that complies with FIRST API
        syntax rules.
    """

    # Start with domain name and parameters separated by slashes
    if session.source == "staging":
        url = session.STAGING_URL
    else:
        url = session.PRODUCTION_URL
    url += "/" + session.FIRST_API_VERSION
    if command == "season":
        url += "/" + str(session.season)
    elif command == "status":
        pass
    else:
        url += "/" + str(session.season) + "/" + command

    # Add GET parameters
    if http_args is not None:
        first_arg = True
        for arg_name, value in http_args.items():
            if value is not None:
                if arg_name[0] == "/":
                    assert first_arg  # url parameters before GET arguments
                    url += "/" + value
                else:
                    url += ("?" if first_arg else "&")
                    if isinstance(value, bool):
                        value = str(value).lower()
                    url += arg_name + "=" + value
                    first_arg = False
    return url


def httpdate_to_datetime(http_date, gmt=True):
    """Converts a HTTP datetime string to a Python datetime object.

    Args:
        http_date: A string formatted as an HTTP date and time.
        gmt: If True, sets timezone of resulting datetime object to
            GMT. Otherwise datetime object is timezone unaware.
            Optional, default is True.

    Returns: A Python datetime object that is timezone aware, set to
        the GMT time zone. Returns False if the http_date argument is
        not a valid HTTP date.

    Raises:
        UserWarning if the http_date argument is not a valid HTTP date
        and time.
    """
    try:
        if gmt:
            dtm = datetime.datetime.strptime(http_date,
                                             "%a, %d %b %Y %H:%M:%S %Z")
        else:
            dtm = datetime.datetime.strptime(http_date,
                                             "%a, %d %b %Y %H:%M:%S")
    except ValueError:
        warn_msg = ("Incorrect date-time format passed as argument. "
                    "Argument has been ignored."
                    "Use HTTP format ('ddd, MMM dd YYYY HH:MM:SS ZZZ') where "
                    "ddd is 3-letter abbreviation for weekday and ZZZ is "
                    "3-digit abbreviaion for time zone.")
        warnings.warn(warn_msg, UserWarning)
        return False
    else:
        if gmt:
            dtm = dtm.replace(
                tzinfo=datetime.timezone(datetime.timedelta(hours=0), "GMT"))
        return dtm


def datetime_to_httpdate(date_time, gmt=True):
    """Converts a Python datetime object to an HTTP datetime string.

    Args:
        date_time: A Python datetime object.
        gmt: If true, http date string will indicate time is in GMT
            timezone. Optional, default value is True.

    Returns: A string formatted as an HTTP datetime, using the GMT
        timezone.
    """
    if gmt:
        tzone_gmt = datetime.timezone(datetime.timedelta(hours=0), "GMT")
        date_time = date_time.replace(tzinfo=tzone_gmt)
        fmt_string = "%a, %d %b %Y %H:%M:%S %Z"
    else:
        fmt_string = "%a, %d %b %Y %H:%M:%S"
    return datetime.datetime.strftime(date_time, fmt_string)


def httpdate_addsec(http_date, gmt=True):
    """Adds one second to an HTTP datetime string.

    Args:
        http_date: An HTTP datetime string.
        gmt: If true, timezone of resulting datetime object will be set
            to GMT. Optional, default is True.

    Returns:
        An HTTP datetime string that is one second later than the
        string passed in the http_date argument.

    Raises:
        ValueError if http_date is not a vallid HTTP datetime string.
    """
    dtm = httpdate_to_datetime(http_date, gmt)
    if dtm:
        dtm_new = dtm + datetime.timedelta(seconds=1)
    else:
        raise ValueError("http_date argument is not a valid HTTP datetime"
                         "string.")
    return datetime_to_httpdate(dtm_new, gmt)


def send_http_request(session, url, cmd, mod_since=None, only_mod_since=None):
    """Sends http request to FIRST API server and returns response.

    send_http_request() is an internal function that is not intended to
    be called by the user. In addition to sending the http request,
    send_http_request() converts the JSON-formatted response text into
    a Pandas dataframe.

    Args:
        session: An instance of fapy.classes.Session that contains
            a valid username and authorization key.
        url: A string containing the url that will be sent to the
            FIRST API server.
        cmd: A string specifying the FIRST API command.
        mod_since: A string containing an HTTP formatted date and time.
            Causes send_http_request() to return None if no changes have been
            made to the requested data since the date and time provided.
            Optional.
        only_mod_since: A string containing an HTTP formatted date and
            time. Causes send_http_request() to only return data that has
            changed since the date and time provided. Optional.

    Returns:
        If session.data_format == "dataframe", returns an instances of
        fapy.classes.FirstDF, which is a Pandas dataframe with
        an `attr` property. The `attr` property is a Python dictionary
        with the keys listed below.
        If session.data_format == "schedule.json" or "xml", returns a Python
        dictionary object with the keys listed below.

        text: The JSON or XML response text.
        url: The URL that was sent to the FIRST API server.
        time_downloaded: The date and time that the data was downloaded
            from the FIRST API server.
        local_data:
        local_time:
        local_url:
    """
    # pylint: disable=too-many-locals
    # Check arguments
    if(mod_since is not None) and (only_mod_since is not None):
        raise ArgumentError("Cannot specify both mod_since and "
                            "only_mod_since arguments.")

    # Create authorization and format headers
    raw_token = session.username + ":" + session.key
    token = "Basic " + base64.b64encode(raw_token.encode()).decode()

    data = {}
    if session.data_format == "xml":
        format_header = "application/xml"
        data["text_format"] = "xml"
    else:
        format_header = "application/schedule.json"
        data["text_format"] = "json"

    hdrs = {"Accept": format_header, "Authorization": token}
    if mod_since is not None and httpdate_to_datetime(mod_since):
        hdrs["If-Modified-Since"] = mod_since
    if only_mod_since is not None and httpdate_to_datetime(only_mod_since):
        hdrs["FMS-OnlyModifiedSince"] = only_mod_since

    # Submit HTTP request
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req) as resp:
            data["code"] = resp.getcode()
            data["text"] = resp.read().decode("utf-8")
            data["url"] = resp.geturl()
            for key, value in resp.info().items():
                data[key] = value
    except urllib.error.HTTPError as err:
        # FIRST API returns 304 if data has not been modified since
        if err.code == 304:
            data["code"] = 304
            data["text"] = None
            data["url"] = url
        else:
            raise

    data["time_downloaded"] = datetime_to_httpdate(datetime.datetime.now(),
                                                   False)
    data["local_data"] = False
    data["local_time"] = None
    data["requested_url"] = data["url"]
    data["frame_type"] = cmd
    data["mod_since"] = mod_since
    data["only_mod_since"] = only_mod_since
    return data


def send_local_request(session, url, cmd):
    """Retrieves a FIRSTResponse object from a local data cache.

    Args:
        session: An instance of fapy.classes.Session that contains
            a valid username and authorization key.
        url: A string containing the url containing all FIRST API
            parameters.
        cmd: A string specifying the FIRST API command.

    Returns: A Response object.
    """

    # Determine API command from URL
    if session.data_format.lower() == "xml":
        filename = cmd + "_xml.pickle"
    else:
        filename = cmd + "_json.pickle"

    os.chdir(
        "C:/Users/stacy/OneDrive/Projects/FIRST_API/fapy/data")
    with open(filename, 'rb') as file:
        local_data = pickle.load(file)

    local_time = datetime_to_httpdate(datetime.datetime.now(), False)
    local_data["local_data"] = True
    local_data["local_time"] = local_time
    local_data["requested_url"] = url
    return local_data


class ArgumentError(Exception):
    """Raised when there are incorrect combinations of arguments.
    """
    pass


class Dframe(pandas.DataFrame):
    """A subclass of pandas.Dataframe with FIRST API metadata attributes.

    Attributes:
        attr: A python Dictionary that contains FIRST API metatadata,
             such as the URL used to download the data and the time
             downloaded.
        frame_type: A string, such as "teams" or "events", that denotes
             the FIRST API command used to download the data, as well
             as the format of the dataframe.
        build: A method that takes a fapy.response object and returns a
            fapy.Dframe.
    """

    # Required because pandas overrides __getattribute__().
    # See http://pandas.pydata.org/pandas-docs/stable/internals.html
    # #subclassing-pandas-data-structures
    metadata = ["attr", "frame_type"]

    def __init__(self, response, record_path=None, meta=None, extract=None):
        """

        Args:
            response: (fapy.Response) The data that will be
                converted to a fapy.DFrame
            record_path: (string) The JSON name that identifies the
                list of objects that will be converted to dataframe
                rows.
            meta: (List of Strings) A list of JSON names that identify
                JSON values that will be added to each dataframe row.
        """
        # Provide a version of constructor that takes dataframe for
        #     pandas.concat function.
        if not isinstance(response, dict):
            super().__init__(response)
            self._attr = None
            return
        if (record_path is None) and (meta is None):
            frame = pandas.read_json("[" + response["text"] + "]",
                                     orient="records", typ="frame")
        else:
            json_data = json.loads(response["text"])
            if extract is not None:
                json_data = json_data[extract]
            frame = pj.json_normalize(json_data, record_path=record_path,
                                      meta=meta)
        super().__init__(frame)
        self._attr = response

    @property
    def _constructor(self):
        """
        Ensures pandas functions return FirstDf instead of Dataframe.

        See http://pandas.pydata.org/pandas-docs/stable/internals.html
        #subclassing-pandas-data-structures

        Returns: FirstDf
        """
        return Dframe

    @property
    def attr(self):
        """Contains FIRST API metadata attributes.

        Examples of metadata attributes includes the time the data was
        downloaded from the FIRST API server, the url used to download
        the data, etc.

        Returns: A Python dictionary.
        """
        return self._attr

    @attr.setter
    def attr(self, attr):
        self._attr = attr
