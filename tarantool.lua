#!/usr/bin/env tarantool
package.path = package.path .. ';/usr/local/lua/tarantool-queue/?.lua'
package.path = package.path .. ';/usr/local/share/lua/5.2/queue/?.lua'


box.cfg {
    listen = '127.0.0.1:3401'
}

box.once('init', function()
    box.schema.user.grant('guest', 'read,write,execute', 'universe')

    local s = box.schema.create_space('orders')
    s:create_index('primary',            {type = 'tree', parts = {1, 'unsigned'}})
    s:create_index('exchange_order',     {type = 'hash', parts = {2, 'str', 4, 'str'}})
    s:create_index('exchange_pairs',     {type = 'tree', unique=false, parts = {3, 'str', 4, 'str'}})
    s:create_index('exchange',           {type = 'tree', unique=false, parts = {4, 'str'}})
    s:create_index('exchange_type',      {type = 'tree', unique=false, parts = {4, 'str', 6, 'str'}})
    s:create_index('exchange_pairs_type',{type = 'tree', unique=false, parts = {4, 'str', 4, 'str', 6, 'str'}})
    s:format({
        {name='id', type='unsigned'},
        {name='order_id', type='string'},
        {name='pair', type='string'},
        {name='exchange', type='string'},
        {name='info', type='array'},
        {name='type', type='string'},
    })
end)


function table.slice(tbl, first, last, step)
    local sliced = {}

    for i = first or 1, last or #tbl, step or 1 do
        sliced[#sliced+1] = tbl[i]
    end

    return sliced
end


function create_job(queue, payload)
    return box.queue.tube[queue]:put(payload)
end


function take_job(queue, timeout)
    return box.queue.tube[queue]:take(timeout)
end


function ack_job(queue, task_id)
    return box.queue.tube[queue]:ack(task_id)
end


function release_job(queue, task_id)
    return box.queue.tube[queue]:release(task_id)
end

queue = require 'queue'
queue.start()
queue.create_tube('orders', 'fifo', {if_not_exists = true})
box.queue = queue

