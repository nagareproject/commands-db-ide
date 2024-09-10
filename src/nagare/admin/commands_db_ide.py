# --
# Copyright (c) 2008-2024 Net-ng.
# All rights reserved.
#
# This software is licensed under the BSD License, as described in
# the file LICENSE.txt, which you should have received as part of
# this distribution.
# --
import inspect
import tempfile
from pathlib import Path

from harlequin import HarlequinKeyMap, app, cli

from nagare import commands
from nagare.admin import command
from nagare.services.database import Database

Database.CONFIG_SPEC['ide'] = {
    'theme': 'string(default="harlequin", help="https://pygments.org/styles")',
    'limit': 'integer(default={}, help="maximum number of records fetched")'.format(cli.DEFAULT_LIMIT),
    'keymap': 'option("{}", default="{}")'.format(','.join(app.load_keymap_plugins([])), cli.DEFAULT_KEYMAP_NAMES[0]),
    '__many__': {'display': 'string(default=None)', 'action': 'string'},
}


class KeysApp(cli.HarlequinKeys):
    _BASE_PATH = inspect.getfile(cli.HarlequinKeys)

    def modified_bindings(self, original_bindings):
        original_bindings = {frozenset(binding.keys.split(',')) for binding in original_bindings}

        return [
            (binding.keys, binding.action, binding.key_display)
            for binding in self.bindings.values()
            if binding.keys and frozenset(binding.keys.split(',')) not in original_bindings
        ]

    async def action_quit(self):
        self.active_keymap_names = []
        await super().action_quit()


class IDE_keys(command.Command):
    DESC = 'Keys definition helper for the SQL IDE'

    @staticmethod
    def create_harlequin_params(theme, limit, keymap, **keys):
        return theme, keymap, ((keys, binding['action'], binding['display']) for keys, binding in keys.items())

    def run(self, database_service):
        theme, keymap, bindings = self.create_harlequin_params(**database_service.plugin_config['ide'])

        with tempfile.NamedTemporaryFile(mode='w') as f:
            for keys, action, display in bindings:
                print('[[keymaps._custom_]]', file=f)
                print(f'keys="{keys}"', file=f)
                print(f'action="{action}"', file=f)
                if display:
                    print(f'key_display="{display}"', file=f)

            f.seek(0)

            keys_app = KeysApp(theme=theme, keymap_name=[keymap, '_custom_'], config_path=Path(f.name))
            keys_app.run()

        print('[database]')
        print('[[ide]]')
        for keys, action, display in keys_app.modified_bindings(app.load_keymap_plugins([])[keymap].bindings):
            print(f'[[[{keys}]]]')
            print(f'action = "{action}"')
            if display:
                print(f'display = "{display}"')
            print()

        return 0


class IDE(command.Command):
    DESC = 'SQL IDE (see http://harlequin.sh)'
    WITH_STARTED_SERVICES = True

    def set_arguments(self, parser):
        parser.add_argument('--db', help='name of the database section')

        super(IDE, self).set_arguments(parser)

    @staticmethod
    def create_harlequin_params(theme, limit, keymap, **keys):
        bindings = [
            {'keys': keys, 'action': binding['action'], 'key_display': binding['display']}
            for keys, binding in keys.items()
        ]

        return {
            'theme': theme,
            'max_results': limit,
            'keymap_names': [keymap, '_custom_'],
            'user_defined_keymaps': [HarlequinKeyMap.from_config('_custom_', bindings)],
        }

    def run(self, database_service, db=None):
        metadatas = {metadata.name: metadata for metadata in database_service.metadatas}

        if not db:
            if len(metadatas) == 1:
                db = next(iter(metadatas))
            else:
                raise commands.ArgumentError('missing --db option')

        engine = database_service.get_engine(metadatas[db])
        if engine.url.drivername.startswith('sqlite'):
            adapter = 'sqlite'
            conn_parameters = {'conn_str': [engine.url.database]}
        elif engine.url.drivername.startswith('postgresql'):
            adapter = 'postgres'
            conn_parameters = {'conn_str': [str(engine.url.set(drivername=adapter))]}
        elif engine.url.drivername.startswith('mysql'):
            adapter = 'mysql'

            url = engine.url
            conn_parameters = {
                'conn_str': (),
                'host': url.host,
                'port': url.port,
                'database': url.database,
                'user': url.username,
                'password': url.password,
            }
        else:
            raise commands.ArgumentError('No IDE available for {} database'.format(engine.url.drivername))

        adapter = cli.load_adapter_plugins()[adapter](**conn_parameters)
        cli.Harlequin(adapter, **self.create_harlequin_params(**database_service.plugin_config['ide'])).run()

        return 0
