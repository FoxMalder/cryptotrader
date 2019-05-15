class Api {
    $fetchTable() {
        return $.ajax(`${window.location.pathname}/table${window.location.search}`);
    }
}

class Table {
    constructor(api, tableSelector) {
        this.api = api;
        this.tableSelector = tableSelector
    }

    update() {
        this.api
            .$fetchTable()
            .done((data) => {
                $(this.tableSelector).html(data);
            });
    }
}

class App {
    constructor(table, interval) {
        this.table = table;
        this.interval = interval;
    }

    init() {
        setInterval(this.table.update, this.interval)
    }
}

let api = new Api();
let table = new Table(api, '.js-table-body');

new App(
    table,
    1000 * 3, // three seconds
).init();
