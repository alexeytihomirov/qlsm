import React, { Fragment } from 'react';
import { Listbox, Transition } from '@headlessui/react';
import { ChevronDown, Check, FileText, Radio } from 'lucide-react';
import { CURRENT_SERVER_LOG, groupArchivesByMonth, formatArchiveLabel } from '../../utils/serverLogArchives';

/**
 * Source picker for the server-log modal: the live log plus rotated archives
 * grouped by month. Archive filenames come only from the server-side listing,
 * and the raw filename is what gets passed back to the caller.
 */
function ServerLogArchivePicker({ files, selectedFile, onSelect, disabled = false }) {
    const groups = groupArchivesByMonth(files);
    const isCurrent = selectedFile === CURRENT_SERVER_LOG;
    const selectedLabel = isCurrent ? 'Current' : formatArchiveLabel(selectedFile, 0);

    return (
        <div className="flex items-center gap-2">
            <span
                className={`font-mono text-[10px] font-bold tracking-wider px-2 py-1 rounded ${
                    isCurrent
                        ? 'bg-[var(--accent-success,#10b981)]/15 text-[var(--accent-success,#10b981)]'
                        : 'bg-[var(--surface-elevated)] text-theme-muted'
                }`}
            >
                {isCurrent ? 'LIVE' : 'ARCHIVED'}
            </span>

            <div className="relative w-44">
                <Listbox value={selectedFile} onChange={onSelect} disabled={disabled}>
                    <div className="relative">
                        <Listbox.Button className="relative w-full cursor-default rounded-lg bg-theme-base/50 py-2 pl-3 pr-10 text-left shadow-md focus:outline-none sm:text-sm border border-white/10 disabled:opacity-50">
                            <span className="block truncate text-theme-primary">{selectedLabel}</span>
                            <span className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-2">
                                <ChevronDown className="h-4 w-4 text-gray-400" aria-hidden="true" />
                            </span>
                        </Listbox.Button>
                        <Transition
                            as={Fragment}
                            leave="transition ease-in duration-100"
                            leaveFrom="opacity-100"
                            leaveTo="opacity-0"
                        >
                            <Listbox.Options className="absolute mt-1 max-h-72 w-full overflow-auto rounded-md bg-theme-bg/95 backdrop-blur-md py-1 text-base shadow-lg ring-1 ring-black/5 focus:outline-none sm:text-sm z-50 border border-white/10 scrollbar-thick">
                                <Listbox.Option
                                    value={CURRENT_SERVER_LOG}
                                    className={({ active }) =>
                                        `relative cursor-default select-none py-2 pl-10 pr-4 ${
                                            active ? 'bg-theme-secondary/20 text-theme-primary' : 'text-theme-secondary'
                                        }`
                                    }
                                >
                                    {({ selected }) => (
                                        <>
                                            <span className={`block truncate ${selected ? 'font-medium text-theme-primary' : 'font-normal'}`}>
                                                Current
                                            </span>
                                            <span className="absolute inset-y-0 left-0 flex items-center pl-3">
                                                {selected
                                                    ? <Check className="h-4 w-4 text-amber-500" aria-hidden="true" />
                                                    : <Radio className="h-4 w-4 text-theme-muted" aria-hidden="true" />}
                                            </span>
                                        </>
                                    )}
                                </Listbox.Option>

                                {groups.map((group) => (
                                    <div key={group.key}>
                                        <div className="px-3 py-1 mt-1 font-mono text-[10px] uppercase tracking-wider text-theme-muted border-t border-white/5">
                                            {group.label}
                                        </div>
                                        {group.items.map((item) => (
                                            <Listbox.Option
                                                key={item.filename}
                                                value={item.filename}
                                                className={({ active }) =>
                                                    `relative cursor-default select-none py-2 pl-10 pr-4 ${
                                                        active ? 'bg-theme-secondary/20 text-theme-primary' : 'text-theme-secondary'
                                                    }`
                                                }
                                            >
                                                {({ selected }) => (
                                                    <>
                                                        <span className={`block truncate ${selected ? 'font-medium text-theme-primary' : 'font-normal'}`}>
                                                            {item.label}
                                                        </span>
                                                        <span className="absolute inset-y-0 left-0 flex items-center pl-3">
                                                            {selected
                                                                ? <Check className="h-4 w-4 text-amber-500" aria-hidden="true" />
                                                                : <FileText className="h-4 w-4 text-theme-muted" aria-hidden="true" />}
                                                        </span>
                                                    </>
                                                )}
                                            </Listbox.Option>
                                        ))}
                                    </div>
                                ))}
                            </Listbox.Options>
                        </Transition>
                    </div>
                </Listbox>
            </div>
        </div>
    );
}

export default ServerLogArchivePicker;
