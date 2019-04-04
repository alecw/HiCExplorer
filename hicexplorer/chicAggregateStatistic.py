import argparse
import sys
import os
import math
import logging
log = logging.getLogger(__name__)

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

import hicmatrix.HiCMatrix as hm
from hicexplorer import utilities
from hicexplorer._version import __version__
from .lib import Viewpoint


def parse_arguments(args=None):
    parser = argparse.ArgumentParser(add_help=False,
                                     description='Aggregates the statistics of interaction files and prepares them for chicDifferentialTest')

    parserRequired = parser.add_argument_group('Required arguments')

    parserRequired.add_argument('--interactionFile', '-if',
                                help='path to the interaction files which should be used for aggregation of the statistics.',
                                required=True,
                                nargs='+')

    parserMutuallyExclusiveGroup = parser.add_mutually_exclusive_group(required=True)
    parserMutuallyExclusiveGroup.add_argument('--targetFile', '-tf',
                                              help='path to the target files which contains the target regions to prepare data for differential analysis.'
                                              )
    parserMutuallyExclusiveGroup.add_argument('--rbzScore', '-rbz',
                                              help='rbzScore threshold value to filter target regins to include them for differential analysis.',
                                              type=float)

    parserOpt = parser.add_argument_group('Optional arguments')

    parserOpt.add_argument('--outFileNameSuffix', '-suffix',
                           help='File name suffix to save the result.',
                           required=False,
                           default='_aggregate_target.bed')
    parserOpt.add_argument('--interactionFileFolder', '-iff',
                           help='Folder where the interaction files are stored in. Applies only for batch mode.',
                           required=False,
                           default='.')
    parserOpt.add_argument('--outputFolder', '-o',
                           help='Output folder of the files.',
                           required=False,
                           default='aggregatedFiles')
    parserOpt.add_argument('--writeFileNamesToFile', '-w',
                           help='',
                           default='aggregatedFilesBatch.txt')
    parserOpt.add_argument('--batchMode', '-bm',
                           help='The given file for --interactionFile and or --targetFile contain a list of the to be processed files.',
                           required=False,
                           action='store_true')
    parserOpt.add_argument("--mergeBins", "-mb",
                           type=int,
                           default=0,
                           help="Merge neighboring interactions to one. The value of this parameter defines the maximum distance"
                           " a neighbor can have. The values are averaged.")

    parserOpt.add_argument("--help", "-h", action="help", help="show this help message and exit")

    parserOpt.add_argument('--version', action='version',
                           version='%(prog)s {}'.format(__version__))
    return parser


def create_target_regions(pInteraction_file_data, pInteraction_file_data_1, pRbzScore):
    # log.debug(pInteraction_file_data)
    accepted_scores_file_1 = []
    accepted_scores_file_2 = []

    # get significant regions
    for key in pInteraction_file_data:
        if float(pInteraction_file_data[key][-2]) >= pRbzScore:
            accepted_scores_file_1.append(key)

    for key in pInteraction_file_data_1:
        if float(pInteraction_file_data_1[key][-2]) >= pRbzScore:
            accepted_scores_file_2.append(key)

    # merge keys
    accepted_scores_file_1.extend(accepted_scores_file_2)
    accepted_scores_file_1 = np.unique(accepted_scores_file_1)

    target_list = []
    for key in accepted_scores_file_1:
        # pInteraction_file_data
        target_list.append(pInteraction_file_data[key][0:3])

    # log.debug('target_list {}'.format(target_list))
    return target_list


def filter_scores_target_list(pScoresDictionary, pTargetRegions):

    accepted_scores = {}
    for target in pTargetRegions:
        start = int(target[1])
        end = int(target[2])
        _accepted_scores = {}
        for key in pScoresDictionary:
            if int(pScoresDictionary[key][1]) >= start and int(pScoresDictionary[key][2]) <= end:
                _accepted_scores[key] = pScoresDictionary[key]

        if len(_accepted_scores) > 0:

            values = np.array([0.0, 0.0, 0.0])
            for key in _accepted_scores:
                values += np.array(list(map(float, _accepted_scores[key][-3:])))
            keys_sorted = sorted(_accepted_scores.keys())
            _accepted_scores[keys_sorted[0]][-5] = _accepted_scores[keys_sorted[-1]][-5]
            _accepted_scores[keys_sorted[0]][-3] = values[0]
            _accepted_scores[keys_sorted[0]][-2] = values[1]
            _accepted_scores[keys_sorted[0]][-1] = values[2]

            accepted_scores[keys_sorted[0]] = _accepted_scores[keys_sorted[0]]

    return accepted_scores


def merge_neighbors(pScoresDictionary, pMergeThreshold=1000):

    key_list = list(pScoresDictionary.keys())

    merge_ids = []
    non_merge = []
    for i, (key_pre, key_suc) in enumerate(zip(key_list[:-1], key_list[1:])):

        if np.absolute(int(pScoresDictionary[key_pre][6]) - int(pScoresDictionary[key_suc][5])) < pMergeThreshold:
            if len(merge_ids) > 0 and merge_ids[-1][-1] == key_pre:
                merge_ids[-1].append(key_suc)
            else:
                merge_ids.append([key_pre, key_suc])
        else:
            if i == len(key_list) - 1:
                non_merge.append(key_suc)
            non_merge.append(key_pre)
    scores_dict = {}
    for element in merge_ids:
        base_element = pScoresDictionary[element[0]]
        values = np.array(list(map(float, base_element[-3:])))
        for key in element[1:]:
            base_element[-5] = pScoresDictionary[key][-5]
            values += np.array(list(map(float, pScoresDictionary[key][-3:])))

        base_element[-3] = values[0]
        base_element[-2] = values[1]
        base_element[-1] = values[2]
        scores_dict[element[0]] = base_element
    for key in non_merge:
        scores_dict[key] = pScoresDictionary[key]

    return scores_dict


def write(pOutFileName, pHeader, pNeighborhoods, pInteractionLines, pScores=None):

    sum_of_interactions = float(pHeader.split('\t')[-1].split(' ')[-1])
    log.debug('sum_of_interactions {}'.format(sum_of_interactions))
    with open(pOutFileName, 'w') as file:
        file.write(pHeader)
        file.write('#ChrInteraction\tStart\tEnd\tRelative distance\tSum of interactions\tRel Inter target\trbz-score target\tRaw target')
        file.write('\n')

        for data in pNeighborhoods:
            # log.debug('pInteractionLines[data] {}'.format(pInteractionLines[data]))
            new_line = '\t'.join(pInteractionLines[data][:4])
            new_line += '\t' + format(float(sum_of_interactions), "10.5f")

            # new_line += '\t' + '\t'.join(format(float(x), "10.5f") for x in pInteractionLines[0][8:])
            new_line += '\t' + format(pNeighborhoods[data][-3], '10.5f') + '\t' + format(pNeighborhoods[data][-2], '10.5f') + '\t' + format(pNeighborhoods[data][-1], '10.5f')
            new_line += '\n'
            file.write(new_line)


def main(args=None):
    args = parse_arguments().parse_args(args)
    viewpointObj = Viewpoint()
    outfile_names = []
    if not os.path.exists(args.outputFolder):
        try:
            os.makedirs(args.outputFolder)
        except OSError as exc:  # Guard against race condition
            if exc.errno != errno.EEXIST:
                raise
    if args.targetFile:
        # read all interaction files.
        if args.batchMode:
            interactionFileList = []
            with open(args.interactionFile[0], 'r') as interactionFile:
                file_ = True
                while file_:
                    # for line in fh.readlines():
                    file_ = interactionFile.readline().strip()
                    # file2_ = interactionFile.readline().strip()
                    if file_ != '':
                        interactionFileList.append(file_)

        else:
            interactionFileList = args.interactionFile

        for interactionFile in interactionFileList:
            header, interaction_data, interaction_file_data = viewpointObj.readInteractionFileForAggregateStatistics(args.interactionFileFolder + '/' + interactionFile)

            target_regions = utilities.readBed(args.targetFile)
            accepted_scores = filter_scores_target_list(interaction_file_data, target_regions)

            if len(accepted_scores) == 0:
                log.error('No target regions found')
                sys.exit(0)
            outFileName = '.'.join(interactionFile.split('.')[:-1]) + '_' + args.outFileNameSuffix
            if args.batchMode:
                outfile_names.append(outFileName)
            outFileName = args.outputFolder + '/' + outFileName

            if args.mergeBins > 0:
                merged_neighborhood = merge_neighbors(accepted_scores, args.mergeBins)
                write(outFileName, header, merged_neighborhood, interaction_file_data)
            else:
                write(outFileName, header, accepted_scores, interaction_file_data)

    elif args.rbzScore:
        interactionFileList = []

        if args.batchMode:
            log.debug('args.interactionFile {}'.format(args.interactionFile))
            with open(args.interactionFile[0], 'r') as interactionFile:

                file_ = True
                while file_:
                    # for line in fh.readlines():
                    file_ = interactionFile.readline().strip()
                    file2_ = interactionFile.readline().strip()
                    if file_ != '' and file2_ != '':
                        interactionFileList.append((file_, file2_))
            log.debug('interactionFileList {}'.format(interactionFileList))
        else:
            if len(args.interactionFile) % 2 == 0:
                i = 0
                while i < len(args.interactionFile):
                    interactionFileList.append((args.interactionFile[i], args.interactionFile[i + 1]))
                    i += 2
            else:
                log.error('Number of interaction files needs to be even: {}'.format(len(args.interactionFile)))
                exit(1)

        # if len(interactionFileList) % 2 == 0 or args.batchMode:

        for interactionFile in interactionFileList:

            # header, interaction_data, interaction_file_data
            data = [viewpointObj.readInteractionFileForAggregateStatistics(args.interactionFileFolder + '/' + interactionFile[0])]
            data.append(viewpointObj.readInteractionFileForAggregateStatistics(args.interactionFileFolder + '/' + interactionFile[1]))

            target_regions = create_target_regions(data[0][2], data[1][2], args.rbzScore)
            sample_prefix = interactionFile[0].split('/')[-1].split('_')[0] + '_' + interactionFile[1].split('/')[-1].split('_')[0]
            log.debug('sample_prefix {}'.format(sample_prefix))
            for j in range(2):
                accepted_scores = filter_scores_target_list(data[j][2], target_regions)

                if len(accepted_scores) == 0:
                    if args.batchMode:
                        with open('errorLog.txt', 'a+') as errorlog:
                            errorlog.write('Failed for: {} and {}.\n'.format(interactionFile[0], interactionFile[1]))
                            break
                    else:
                        log.error('No target regions found')
                        sys.exit(0)
                outFileName = '.'.join(interactionFile[j].split('/')[-1].split('.')[:-1]) + '_' + sample_prefix + args.outFileNameSuffix

                if args.batchMode:
                    outfile_names.append(outFileName)
                outFileName = args.outputFolder + '/' + outFileName

                if args.mergeBins > 0:
                    merged_neighborhood = merge_neighbors(accepted_scores, args.mergeBins)
                    write(outFileName, data[j][0], merged_neighborhood, data[j][2])
                else:
                    write(outFileName, data[j][0], accepted_scores, data[j][2])
        # else:
        #     log.error('Number of interaction files needs to be even: {}'.format(len(interactionFileList)))
        #     exit(1)

    if args.batchMode:
        with open(args.writeFileNamesToFile, 'w') as nameListFile:
            nameListFile.write('\n'.join(outfile_names))
