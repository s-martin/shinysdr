# Copyright 2013, 2014, 2015, 2016, 2017, 2018 Kevin Reid and the ShinySDR contributors
#
# This file is part of ShinySDR.
# 
# ShinySDR is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# ShinySDR is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with ShinySDR.  If not, see <http://www.gnu.org/licenses/>.

# pylint: disable=maybe-no-member, no-member
# (maybe-no-member: GR swig)
# (no-member: Twisted reactor)

from __future__ import absolute_import, division, print_function, unicode_literals

from collections import namedtuple
import json
import os.path

import six

from twisted.internet import task
from twisted.python.url import URL
from twisted.web import static
from twisted.web.client import Agent, readBody
from zope.interface import Interface, implementer

from shinysdr.devices import Device, IComponent
from shinysdr.interfaces import ClientResourceDef
from shinysdr.telemetry import ITelemetryMessage, ITelemetryObject, TelemetryItem, Track, empty_track
from shinysdr.types import TimestampT
from shinysdr.values import ExportedState, exported_value, setter

_POLLING_INTERVAL = 8
drop_unheard_timeout_seconds = 60


_SECONDS_PER_HOUR = 60 * 60
_METERS_PER_NAUTICAL_MILE = 1852
_KNOTS_TO_METERS_PER_SECOND = _METERS_PER_NAUTICAL_MILE / _SECONDS_PER_HOUR
_CM_PER_INCH = 2.54
_INCH_PER_FOOT = 12
_METERS_PER_FEET = (_CM_PER_INCH * _INCH_PER_FOOT) / 100
_FEET_PER_MINUTE_TO_METERS_PER_SECOND = _METERS_PER_FEET * 60
_BASE_URL = 'https://data-live.flightradar24.com/zones/fcgi/feed.js?faa=1&mlat=1&flarm=1&adsb=1&gnd=0&air=1&vehicles=0&estimated=1&maxage=14400&gliders=1&stats=0'


def Flightradar24(reactor, key='flightradar24', bounds=None, base_url=_BASE_URL):
    """Create a flightradar24 client.

    key: Component ID.
    bounds: optional 4-element tuple of (lat1, lat2, lon1, lon2) to restrict search
    base_url: optional URL to override the source of the data feed
    """
    return Device(components={six.text_type(key): _Flightradar24Client(
        reactor=reactor,
        bounds=bounds,
        base_url=base_url)})


@implementer(IComponent)
class _Flightradar24Client(ExportedState):
    def __init__(self, reactor, bounds, base_url=_BASE_URL):
        self.__reactor = reactor
        self.__agent = Agent(reactor)
        self.__bounds = bounds
        self.__device_contexts = []
        self.__loop = None
        self.__url = URL.fromText(base_url)

    @exported_value(type=bool, changes='this_setter', label='Enabled')
    def get_enabled(self):
        return self.__loop is not None

    @setter
    def set_enabled(self, enabled):
        if enabled and not self.__loop:
            self.__loop = task.LoopingCall(self.__send_request)
            self.__loop.clock = self.__reactor
            self.__loop.start(_POLLING_INTERVAL).addErrback(print)
        elif not enabled and self.__loop:
            self.__loop.stop()
            self.__loop = None

    def close(self):
        if self.__loop:
            self.__loop.stop()
            self.__loop = None

    def attach_context(self, device_context):
        """implements IComponent"""
        self.__device_contexts.append(device_context)

    def __make_url(self):
        u = self.__url
        if self.__bounds:
            u = u.set('bounds', ','.join(str(b) for b in self.__bounds))
        return six.binary_type(u.asText())

    def __send_request(self):
        if not self.__device_contexts:
            return
        d = self.__agent.request(six.binary_type('GET'), self.__make_url())
        d.addCallback(readBody)
        
        def process(body):
            data = json.loads(body)
            for object_id, aircraft in six.iteritems(data):
                if not isinstance(aircraft, list):
                    continue
                for c in self.__device_contexts:
                    c.output_message(AircraftWrapper(object_id, aircraft))
        d.addCallback(process)
        d.addErrback(print)


@implementer(ITelemetryMessage)
class AircraftWrapper(object):
    def __init__(self, object_id, message):
        self.object_id = object_id
        self.message = message  # list
    
    def get_object_id(self):
        # TODO: add prefix to ensure uniqueness?
        return self.object_id
    
    def get_object_constructor(self):
        return Aircraft


class IAircraft(Interface):
    """marker interface for client"""
    pass


FlightInfo = namedtuple('FlightInfo', [
    'callsign',  # ICAO ATC call signature
    'registration',
    'origin',  # airport IATA code
    'destination',  # airport IATA code
    'flight',
    'squawk_code',  # https://en.wikipedia.org/wiki/Transponder_(aeronautics)
    'model',  # ICAO aircraft type designator
])


empty_flight_info = FlightInfo(
    None,
    None,
    None,
    None,
    None,
    None,
    None,
)


@implementer(IAircraft, ITelemetryObject)
class Aircraft(ExportedState):
    def __init__(self, object_id):
        """Implements ITelemetryObject. object_id is the hex formatted address."""
        self.__last_heard_time = None
        self.__track = empty_track
        self.__flight_info = empty_flight_info
    
    # not exported
    def receive(self, message_wrapper):
        d = message_wrapper.message
        # Fields from https://github.com/derhuerst/flightradar24-client/blob/master/lib/radar.js
 
        timestamp = d[10]

        # Part of self.__track
        latitude = d[1]
        longitude = d[2]
        altitude = d[4]  # in feet
        bearing = d[3]  # in degrees
        speed = d[5]  # in knots
        rate_of_climb = d[15]  # ft/min

        # Shown separately
        callsign = d[16]  # ICAO ATC call signature
        registration = d[9]
        origin = d[11]  # airport IATA code
        destination = d[12]  # airport IATA code
        flight = d[13]
        squawk_code = d[6]  # https://en.wikipedia.org/wiki/Transponder_(aeronautics)
        model = d[8]  # ICAO aircraft type designator

        # Unused
        #is_on_ground = bool(d[14])
        #mode_s_code = d[0]  # // ICAO aircraft registration number
        #radar = d[7]  # F24 "radar" data source ID
        #is_glider = bool(d[17])

        new = {}
        if latitude and longitude:
            new.update(
                latitude=TelemetryItem(latitude, timestamp),
                longitude=TelemetryItem(longitude, timestamp),
            )
        if altitude:
            new.update(altitude=TelemetryItem(altitude * _METERS_PER_FEET, timestamp))
        if speed:
            new.update(h_speed=TelemetryItem(speed * _KNOTS_TO_METERS_PER_SECOND, timestamp))
        if bearing:
            new.update(
                heading=TelemetryItem(bearing, timestamp),
                track_angle=TelemetryItem(bearing, timestamp),
            )
        if rate_of_climb:
            new.update(v_speed=TelemetryItem(rate_of_climb * _FEET_PER_MINUTE_TO_METERS_PER_SECOND, timestamp))
        if new:
            self.__track = self.__track._replace(**new)
        
        self.__last_heard_time = timestamp
        self.__flight_info = FlightInfo(
            callsign=callsign,
            registration=registration,
            origin=origin,
            destination=destination,
            flight=flight,
            squawk_code=squawk_code,
            model=model,
        )
        self.state_changed()
    
    def is_interesting(self):
        """
        Implements ITelemetryObject. Does this aircraft have enough information to be worth mentioning?
        """
        # TODO: Loosen this rule once we have more efficient state transfer (no polling) and better UI for viewing them on the client.
        return \
            self.__track.latitude.value is not None or \
            self.__track.longitude.value is not None or \
            self.__flight_info.callsign is not None or \
            self.__flight_info.registration is not None
    
    def get_object_expiry(self):
        """implement ITelemetryObject"""
        return self.__last_heard_time + drop_unheard_timeout_seconds
    
    @exported_value(type=TimestampT(), changes='explicit', sort_key='100', label='Last heard')
    def get_last_heard_time(self):
        return self.__last_heard_time
    
    @exported_value(type=FlightInfo, changes='explicit', sort_key='020')
    def get_flight_info(self):
        return self.__flight_info
    
    @exported_value(type=Track, changes='explicit', sort_key='010', label='')
    def get_track(self):
        return self.__track


plugin_client = ClientResourceDef(
    key=__name__,
    resource=static.File(os.path.join(os.path.split(__file__)[0], 'client')),
    load_js_path='flightradar24.js')
