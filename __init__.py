#!/usr/bin/env python3
# vim: set encoding=utf-8 tabstop=4 softtabstop=4 shiftwidth=4 expandtab
#########################################################################
#  Copyright 2024-      Michael Wenzel              wenzel_michael@web.de
#########################################################################
#  This file is part of SmartHomeNG.
#  https://www.smarthomeNG.de
#  https://knx-user-forum.de/forum/supportforen/smarthome-py
#
#  Plugin to connect to HomeConnect devices locally (without cloud)
#
#  SmartHomeNG is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  SmartHomeNG is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with SmartHomeNG. If not, see <http://www.gnu.org/licenses/>.
#
#########################################################################


import os
from .HCDevice import *
from .HCSocket import *

from lib.model.smartplugin import SmartPlugin
from lib.item import Items

from .webif import WebInterface


DEVICE_INFO = 'device_info'
INTERFACE_INFO = 'interface_info'
STATUS_INFO = 'status_info'


class HomeConnect(SmartPlugin):
    """
    Main class of the Plugin. Does all plugin specific stuff and provides
    the update functions for the items

    HINT: Please have a look at the SmartPlugin class to see which class properties and methods (class variables and class functions) are already available!
    """

    PLUGIN_VERSION = '1.0.0'

    def __init__(self, sh):
        """
        Initializes the plugin.
        """

        # Call init code of parent class (SmartPlugin)
        super().__init__()

        self.alive = None
        self.cycle = self.get_parameter_value('cycle')
        self.device_name = self.get_parameter_value('device_name')
        self.device_config = None
        self.device = {}
        self.polling_is_busy = False

        # get device config
        config_file = f"{os.getcwd()}/plugins/{self.get_shortname()}/config/devices.json"
        try:
            with open(config_file, "r") as f:
                devices_config = json.load(f)
        except Exception as e:
            self.logger.warning(f"Failed to load config file {e}.")
            self._init_complete = False
            self.deinit()
        else:
            for device in devices_config:
                if device.get('name').lower() == self.device_name.lower():
                    self.device_config = device

            self.device_host = self.device_config["host"]

        # if you want to use an item to toggle plugin execution, enable the definition in plugin.yaml and uncomment the following line
        self._pause_item_path = self.get_parameter_value('pause_item')

        self.init_webinterface(WebInterface)
        return

    def run(self):
        """
        Run method for the plugin
        """
        self.logger.info(self.translate("Methode '{method}' aufgerufen", {'method': 'run()'}))

        if self.cycle == 0:
            self.logger.info(f"Plugin will listen to messages pushed by {self.device_name}")
            self.connect_device()
        else:
            self.logger.info(f"Plugin will poll messages from {self.device_name} every {self.cycle}s.")
            self.scheduler_add(self.get_fullname() + '_poll', self.poll_device, cycle=self.cycle)

        self.alive = True

        if self._pause_item:
            self._pause_item(False, self.get_fullname())

    def stop(self):
        """
        Stop method for the plugin
        """

        self.logger.info(self.translate("Methode '{method}' aufgerufen", {'method': 'stop()'}))
        self.alive = False

        if self._pause_item:
            self._pause_item(True, self.get_fullname())

        self.scheduler_remove_all()

    def parse_item(self, item):
        """
        Default plugin parse_item method. Is called when the plugin is initialized.
        The plugin can, corresponding to its attribute keywords, decide what to do with
        the item in future, like adding it to an internal array for future reference
        :param item:    The item to process.
        :return:        If the plugin needs to be informed of an items change you should return a call back function
                        like the function update_item down below. An example when this is needed is the knx plugin
                        where parse_item returns the update_item function when the attribute knx_send is found.
                        This means that when the items value is about to be updated, the call back function is called
                        with the item, caller, source and dest as arguments and in case of the knx plugin the value
                        can be sent to the knx with a knx write function within the knx plugin.
        """
        # check for pause item
        if item.property.path == self._pause_item_path:
            self.logger.debug(f'pause item {item.property.path} registered')
            self._pause_item = item
            self.add_item(item, updating=True)
            return self.update_item

        # handle all items with hcl_status_info
        if self.has_iattr(item.conf, 'hcl_status_info'):
            self.logger.debug(f"parse item: {item}")

            item_attr = STATUS_INFO
            device_att_value = self.get_iattr_value(item.conf, 'hcl_device').lower()
            item_attr_value = self.get_iattr_value(item.conf, 'hcl_status_info').lower()

        # handle all items with hcl_device_info
        elif self.has_iattr(item.conf, 'hcl_device_info'):
            self.logger.debug(f"parse item: {item}")

            item_attr = DEVICE_INFO
            device_att_value = self.get_iattr_value(item.conf, 'hcl_device').lower()
            item_attr_value = self.get_iattr_value(item.conf, 'hcl_device_info').lower()

        # handle all items with hcl_interface_info
        elif self.has_iattr(item.conf, 'hcl_interface_info'):
            self.logger.debug(f"parse item: {item}")

            item_attr = INTERFACE_INFO
            device_att_value = self.get_iattr_value(item.conf, 'hcl_device').lower()
            item_attr_value = self.get_iattr_value(item.conf, 'hcl_interface_info').lower()

        else:
            return

        if not device_att_value:
            self.logger.warning(f'Bei item {item.path()} fehlt die Angabe des hcl_device als Attribut.')

        # create item config dict
        item_config_data_dict = {'device': device_att_value, 'i_attr': item_attr, 'i_attr_value': item_attr_value}
        self.logger.debug(f"{item.path()} for plugin with {item_config_data_dict=} registered.")

        # add item
        self.add_item(item, config_data_dict=item_config_data_dict, updating=True)

        return self.update_item

    def parse_logic(self, logic):
        """
        Default plugin parse_logic method
        """
        pass

    def update_item(self, item, caller=None, source=None, dest=None):
        """
        Item has been updated

        This method is called, if the value of an item has been updated by SmartHomeNG.
        It should write the changed value out to the device (hardware/interface) that
        is managed by this plugin.

        To prevent a loop, the changed value should only be written to the device, if the plugin is running and
        the value was changed outside of this plugin(-instance). That is checked by comparing the caller parameter
        with the fullname (plugin name & instance) of the plugin.

        :param item: item to be updated towards the plugin
        :param caller: if given it represents the callers name
        :param source: if given it represents the source
        :param dest: if given it represents the dest
        """
        # check for pause item
        if item is self._pause_item:
            if caller != self.get_shortname():
                self.logger.debug(f'pause item changed to {item()}')
                if item() and self.alive:
                    self.stop()
                elif not item() and not self.alive:
                    self.run()
            return

        if self.alive and caller != self.get_fullname():
            # code to execute if the plugin is not stopped and only, if the item has not been changed by this plugin:
            self.logger.info(f"update_item: '{item.property.path}' has been changed outside this plugin by caller '{self.callerinfo(caller, source)}'")
            pass

    def connect_device(self, debug: bool = True):

        self.logger.debug(f"Connect to: {self.device_name} and listen continuously.")

        try:
            self.logger.debug(f"{self.device_name} connecting to {self.device_host}")
            ws = HCSocket(self.device_host, self.device_config["key"], self.device_config.get("iv", None), debug=debug, logger=self.logger)
            device = HCDevice(ws, self.device_config, debug=debug, logger=self.logger)
            device.run_forever(on_message=self._on_message, on_open=self._on_open, on_close=self._on_close)
        except Exception as e:
            self.logger.debug(f"{self.device_name} ERROR: {e}")

    def _on_message(self, msg):
        # print(f"_on_message: \n{json.dumps(msg, sort_keys=True, indent=4)}\n")
        self.logger.debug(f"_on_message: {msg}")

        if msg and 'error' not in msg:
            # handle device data
            if 'deviceID' in msg:
                msg_key = DEVICE_INFO

            # handle network interface data
            elif 'interfaceID' in msg:
                msg_key = INTERFACE_INFO

            # handle status data
            else:
                msg_key = STATUS_INFO

            if msg_key not in self.device:
                self.device[msg_key] = {}

            _merge_dicts(self.device[msg_key], _lower_dict_keys(msg))
            self.update_item_values()

    def _on_open(self, ws):
        self.logger.info(f"{self.device_name} websocket opened...")

    def _on_close(self, ws, code, message):
        self.logger.info(f"{self.device_name} websocket closed. Try to reconnect.")

    def poll_device(self, debug: bool = True):

        if self.polling_is_busy:
            self.logger.warning(f"Another polling cycle of {self.device_name} still running. This poll will be skipped.")
            return

        self.polling_is_busy = True
        self.logger.debug(f"Connect to: {self.device_name} and poll status.")

        try:
            self.logger.debug(f"{self.device_name} connecting to {self.device_host}")
            ws = HCSocket(self.device_host, self.device_config["key"], self.device_config.get("iv", None), debug=debug, logger=self.logger)
            device = HCDevice(ws, self.device_config, debug=debug, logger=self.logger)

            ws.debug = debug
            ws.reconnect()

            while True:
                self._on_message(device.recv())

        except Exception as e:
            self.logger.debug(f"{self.device_name} ERROR: {e}")

        self.polling_is_busy = False

    def update_item_values(self):

        # get relevant item list concerning dedicated device
        device_item_list = self._get_device_item_list()

        # loop through item list and get values from dict
        for item in device_item_list:
            item_config = self.get_item_config(item)
            i_attr = item_config['i_attr']
            i_attr_value = item_config['i_attr_value']

            value = self._get_value_from_device_dict(i_attr, i_attr_value)
            if value:
                item_config['value'] = value
                item(value, self.get_shortname())

    def _get_device_item_list(self):
        return self.get_item_list(filter_key='device', filter_value=self.device_name)

    def _get_value_from_device_dict(self, i_attr, i_attr_value):
        """ get value from device dict and modify diverse values"""

        value = self.device.get(i_attr, {})
        path_list = i_attr_value.split('.')
        for path in path_list:
            value = value.get(path, {})

        if 'programprogress' in path_list:
            # "RemoteControlLevel"
            # "RejectEvent"
            # "DeactivateWiFi"
            # "AllowBackendConnectiom"
            # "BackendConnected"
            # "AcknowledgeEvent"
            value = ''

        elif 'remaining_program_time' in path_list:
            if value.lower() == 'programfinished':
                value = 0

        return value


def _merge_dicts(_dict1, _dict2):
    """Merges two dictionaries recursively.

    Args:
        _dict1: The first dictionary.
        _dict2: The second dictionary.

    Returns:
        A new dictionary containing the merged data.
    """

    for _key, _value in _dict2.items():
        if _key in _dict1:
            if isinstance(_dict1[_key], dict) and isinstance(_value, dict):
                _merge_dicts(_dict1[_key], _value)
            else:
                _dict1[_key] = _value
        else:
            _dict1[_key] = _value

    return _dict1


def _lower_dict_keys(test_dict):
    _res = dict()
    for key in test_dict.keys():
        if isinstance(test_dict[key], dict):
            _res[key.lower()] = _lower_dict_keys(test_dict[key])
        else:
            _res[key.lower()] = test_dict[key]
    return _res
