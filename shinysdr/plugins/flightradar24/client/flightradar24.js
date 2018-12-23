// Copyright 2014, 2015, 2016, 2017 Kevin Reid and the ShinySDR contributors
// 
// This file is part of ShinySDR.
// 
// ShinySDR is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
// 
// ShinySDR is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
// 
// You should have received a copy of the GNU General Public License
// along with ShinySDR.  If not, see <http://www.gnu.org/licenses/>.

'use strict';

define([
  'require',
  'map/map-core',
  'widgets',
  'widgets/basic',
], (
  require,
  import_map_core,
  widgets,
  import_widgets_basic
) => {
  const {
    register,
    renderTrackFeature,
  } = import_map_core;
  const {
    SimpleElementWidget,
    Block,
  } = import_widgets_basic;
  
  const exports = {};

  function FlightInfoWidget(config) {
    SimpleElementWidget.call(this, config, 'DIV',
      function buildPanelForFlightInfo(container) {
        return container.appendChild(document.createElement('DIV'));
      },
      function initEl(valueEl, target) {
        /*
          BOX451 / 3S451 (JFK / FRA)
          B77L D-AALB
          Squawk 1714
        */
        function addDiv() {
          let div = valueEl.appendChild(document.createElement('div'));
          let textNode = document.createTextNode('');
          div.appendChild(textNode);
          return textNode;
        }
        var row1 = addDiv();
        var row2 = addDiv();
        var row3 = addDiv();
        return function updateEl(flight_info) {
          row1.data = `${flight_info.callsign} / ${flight_info.flight}`;
          if (flight_info.origin || flight_info.destination) {
            row1.data += ` (${flight_info.origin || '???'} / ${flight_info.destination || '???'})`;
          }
          row2.data = `${flight_info.model} ${flight_info.registration}`;
          row3.data = `Squawk ${flight_info.squawk_code}`;
        };
      });
  }
  
  function AircraftWidget(config) {
    Block.call(this, config, function (block, addWidget, ignore, setInsertion, setToDetails, getAppend) {
      addWidget('track', widgets.TrackWidget);
      addWidget('flight_info', FlightInfoWidget);
    }, false);
  }
  
  // TODO: Better widget-plugin system so we're not modifying should-be-static tables
  widgets['interface:shinysdr.plugins.flightradar24.IAircraft'] = AircraftWidget;
  
  function addAircraftMapLayer(mapPluginConfig) {
    mapPluginConfig.addLayer('flightradar24', {
      featuresCell: mapPluginConfig.index.implementing('shinysdr.plugins.flightradar24.IAircraft'),
      featureRenderer: function renderAircraft(aircraft, dirty) {
        let trackCell = aircraft.track;
        let flight_info = aircraft.flight_info.depend(dirty);
        let callsign = flight_info.callsign;
        let ident = flight_info.squawk_code;
        let altitude = trackCell.depend(dirty).altitude.value;
        var labelParts = [];
        if (callsign !== null) {
          labelParts.push(callsign.replace(/^ | $/g, ''));
        }
        if (ident !== null) {
          labelParts.push(ident);
        }
        if (altitude !== null) {
          labelParts.push(altitude.toFixed(0) + ' m');
        }
        var f = renderTrackFeature(dirty, trackCell,
          labelParts.join(' • '));
        f.iconURL = require.toUrl('./aircraft.svg');
        return f;
      }
    });
  }
  
  register(addAircraftMapLayer);
  
  return Object.freeze(exports);
});
