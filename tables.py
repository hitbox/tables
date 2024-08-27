import os

import flask.views
import markupsafe
import sqlalchemy as sa
import sqlalchemy.orm
import wtforms

class Base(sa.orm.DeclarativeBase):
    pass


class Item(Base):

    __tablename__ = 'items'

    id = sa.Column(
        sa.Integer,
        primary_key = True,
    )

    name = sa.Column(
        sa.String,
        nullable = False,
        unique = True,
        info = dict(
            th = dict(
                text = 'Name',
            ),
        ),
    )

    price = sa.Column(
        sa.Integer,
        info = dict(
            th = dict(
                text = 'Price',
            ),
        ),
    )


class Account(Base):

    __tablename__ = 'accounts'

    id = sa.Column(
        sa.Integer,
        primary_key = True,
    )

    name = sa.Column(
        sa.String,
        nullable = False,
        unique = True,
        info = dict(
            th = dict(
                text = 'Name',
            ),
        ),
    )

    orders = sa.orm.relationship(
        'Order',
        back_populates = 'account',
    )


class Order(Base):

    __tablename__ = 'orders'

    id = sa.Column(
        sa.Integer,
        primary_key = True,
    )

    account_id = sa.Column(
        sa.ForeignKey('accounts.id'),
    )

    account = sa.orm.relationship(
        'Account',
        back_populates = 'orders',
    )

    items = sa.orm.relationship(
        Item,
        secondary = 'orders_items',
    )


class OrderItem(Base):

    __tablename__ = 'orders_items'

    id = sa.Column(sa.Integer, primary_key=True)
    order_id = sa.Column(sa.ForeignKey(Order.id))
    item_id = sa.Column(sa.ForeignKey(Item.id))


class Table:
    pass


class ModelTableConversionError(Exception):
    pass


class ModelTableConverterBase:

    def __init__(self, converters, use_mro=True):
        self.use_mro = use_mro

        if not converters:
            converters = {}

        for name in dir(self):
            obj = getattr(self, name)
            if hasattr(obj, '_converter_for'):
                for classname in obj._converter_for:
                    converters[classname] = obj

    def get_converter(self, column):
        if self.use_mro:
            types = inspect.getmro(type(column.type))
        else:
            types = [type(column.type)]

        # search by module + name
        for col_type in types:
            type_string = f'{col_type.__module__}.{col_type.__name__}'

            # remove sqlalchemy prefix
            if type_string.startswith('sqlalchemy.'):
                type_string = type_string[11:]

            if type_string in self.converters:
                return self.converters[type_string]

        # search by name
        for col_type in types:
            if col_type.__name__ in self.converters:
                return self.converters[col_type.__name__]

        raise ModelTableConversionError(
            f'No converter found for {column.name} ({types[0]:r})'
        )

    def convert(self, model, mapper, prop, field_args, db_session=None):
        if not hasattr(prop, 'columns') and not hasattr(prop, 'direction'):
            return

        if not hasattr(prop, 'direction') and len(prop.columns) != 1:
            raise TypeError(f'Multiple-column properties not supported.')

        kwargs = {}

        if field_args:
            kwargs.update(field_args)

        converter = None
        column = None

        if hasattr(prop, 'direction'):
            if db_session is None:
                raise ModelTableConversionError(
                    f'Cannot convert field {prop.key}, need database session.'
                )

            foreign_model = prop.mapper.class_

            converter = self.converters[prop.direction.name]

        return converter(
            model = model,
            mapper = mapper,
            prop = prop,
            column = column,
            field_args = field_args,
        )


def converts(*args):
    def _inner(func):
        return func
    return _inner

class ModelTableConverter(ModelTableConverterBase):

    def __init__(self, extra_converters=None, use_mro=True):
        super().__init__(extra_converters, use_mro)

    @converts('String')
    def conv_String(self, field_args, **extra):
        return


class MetadataView(flask.views.View):
    """
    Generate views for tables from SQLAlchemy metadata.
    """

    def __init__(self, base_class):
        self.base_class = base_class

    def dispatch_request(self, tablename=None):
        metadata = self.base_class.metadata
        if tablename is None:
            return self.dispatch_list()
        elif tablename in metadata.tables:
            return self.dispatch_table(tablename)
        else:
            # not found
            flask.abort(404)

    def dispatch_list(self):
        metadata = self.base_class.metadata
        # unordered list of links
        elements = []
        for tablename in metadata.tables:
            class_ = mapped_class_from_tablename(Base, tablename)
            url = flask.url_for(flask.request.endpoint, tablename=tablename)
            text = class_.__name__
            elements.append(f'<li><a href="{url}">{text}</a></li>')
        html = '<ul>' + ''.join(elements) + '</ul>'
        return html

    def dispatch_table(self, tablename):
        # table of instances for table name
        class_ = mapped_class_from_tablename(Base, tablename)
        stmt = sa.select(class_)
        with sa.orm.Session(engine) as session:
            instances = session.scalars(stmt)
            html = markupsafe.Markup(f'<h1>{tablename}</h1>')
            html += html_table(class_, instances, db_session=session)
            return html


def mapped_class_from_tablename(base, tablename):
    for mapper in base.registry.mappers:
        if mapper.persist_selectable.name == tablename:
            return mapper.class_

def model_columns(model):
    mapper = sa.inspect(model)

    properties = list(mapper.attrs.items())

    field_dict = {}
    for name, prop in properties:
        pass

    return field_dict

def model_table(
    model_class,
    type_name = None,
    bases = None,
):
    if type_name is None:
        type_name = model_class.__name__ + 'Table'

    if bases is None:
        bases = (Table, )

    attributes = model_columns(model_class)

    return type(type_name, bases, attributes)

def key_from_property(prop):
    if not hasattr(prop, 'columns') and not hasattr(prop, 'direction'):
        return

    if not hasattr(prop, 'direction') and len(prop.columns) != 1:
        raise TypeError(f'Multiple-column properties not supported.')

    return prop.key

def th_from_property(prop):
    if hasattr(prop, 'direction'):
        foreign_model = prop.mapper.class_
        text = markupsafe.escape(foreign_model.__name__)
    else:
        column = prop.columns[0]
        if column.info and 'th' in column.info and 'text' in column.info['th']:
            text = column.info['th']['text']
        else:
            text = column.name
    return text

def ul(items):
    texts = map(markupsafe.escape, items)
    lis = ''.join(f'<li>{text}</li>' for text in texts)
    return markupsafe.Markup('<ul>' + lis + '</ul>')

def td(obj):
    if isinstance(obj, (list, set, tuple)):
        return td(ul(obj))
    else:
        text = markupsafe.escape(obj)
        return f'<td>{text}</td>'

def html_table(model, instances, db_session=None):
    mapper = sa.inspect(model)
    props = mapper.attrs.values()
    column_keys = [prop.key for prop in props]
    texts = map(th_from_property, props)
    th_list = ''.join(f'<th>{text}</th>' for text in texts)

    header_row = f'<tr>{th_list}</tr>'

    body_rows = []
    for inst in instances:
        db_session.merge(inst)
        tds = list(td(getattr(inst, key)) for key in column_keys)

        body_rows.append(f'<tr>{"".join(tds)}</tr>')

    table_html = '<table><thead>'
    table_html += header_row + '</thead>'
    table_html += f'<tbody>{"".join(body_rows)}</tbody></table>'

    return markupsafe.Markup(table_html)

item_table = model_table(Item)

database = os.environ['TABLES_DATABASE_URL']
engine = sa.create_engine(database)
Base.metadata.create_all(engine)

def add_commands(app):
    @app.cli.command('init_data')
    def init_data():
        with sa.orm.Session(engine) as session:
            # add accounts
            account1 = Account(name='account1')
            account2 = Account(name='account2')
            account3 = Account(name='account3')
            account4 = Account(name='account4')
            session.add_all([account1, account2, account3, account4])
            # add items
            pencil = Item(name='Pencil', price=10)
            notebook = Item(name='Notebook', price=50)
            eraser = Item(name='Eraser', price=15)
            straight_edge = Item(name='Straight Edge', price=50)
            protractor = Item(name='Protractor', price=50)
            desk = Item(name='Desk', price=10_000)
            chair = Item(name='Chair', price=5_000)
            session.add_all([pencil, notebook, eraser, straight_edge, protractor, desk, chair])
            # add orders
            session.add(Order(account=account1, items=[pencil, notebook]))

            session.commit()

def add_pluggables(app):
    view_func = MetadataView.as_view('tables', Base)
    app.add_url_rule('/tables/', view_func=view_func)
    app.add_url_rule('/tables/<tablename>', view_func=view_func)

def create_app():
    app = flask.Flask(__name__)

    add_commands(app)
    add_pluggables(app)

    return app
