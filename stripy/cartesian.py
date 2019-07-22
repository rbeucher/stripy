"""
Copyright 2017-2019 Louis Moresi, Ben Mather

This file is part of Stripy.

Stripy is free software: you can redistribute it and/or modify
it under the terms of the GNU Lesser General Public License as published by
the Free Software Foundation, either version 3 of the License, or any later version.

Stripy is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License
along with Stripy.  If not, see <http://www.gnu.org/licenses/>.
"""

#!/usr/bin/python
# -*- coding: utf-8 -*-
from . import _tripack
from . import _srfpack
import numpy as np

try: range = xrange
except: pass

_ier_codes = {0:  "no errors were encountered.",
              -1: "N < 3 on input.",
              -2: "the first three nodes are collinear.\nSet permute to True or reorder nodes manually.",
              -3: "duplicate nodes were encountered.",
              -4: "an error flag was returned by a call to SWAP in ADDNOD.\n \
                   This is an internal error and should be reported to the programmer.",
              'L':"nodes L and M coincide for some M > L.\n \
                   The linked list represents a triangulation of nodes 1 to M-1 in this case.",
              1: "NCC, N, NROW, or an LCC entry is outside its valid range on input.",
              2: "the triangulation data structure (LIST,LPTR,LEND) is invalid.",
              'K': 'NPTS(K) is not a valid index in the range 1 to N.',
              9999: "Triangulation encountered duplicate nodes."}


class Triangulation(object):
    """
    Define a Delaunay triangulation for given Cartesian mesh points (x, y)
    where x and y vectors are 1D numpy arrays of equal length.

    Algorithm:
        R. J. Renka (1996), Algorithm 751; TRIPACK: a constrained two-
        dimensional Delaunay triangulation package,
        ACM Trans. Math. Softw., 22(1), pp 1-8,
        doi:10.1145/225545.225546.

    Args:
        x : 1D array
            Cartesian x coordinates
        y : 1D array
            Cartesian y coordinates
        refinement_levels : int
            refine the number of points in the triangulation
            (see uniformly_refine_triangulation)
        permute : bool
            randomises the order of lons and lats to improve
            triangulation efficiency and eliminate colinearity
            issues (see notes)
        tree : bool
            construct a cKDtree for efficient nearest-neighbour lookup

    Attributes:
        x : array of floats, shape (n,)
            stored Cartesian x coordinates from input
        y : array of floats, shape (n,)
            stored Cartesian y coordinates from input
        simplices : array of ints, shape (nsimplex, 3)
            indices of the points forming the simplices in the triangulation
            points are ordered anticlockwise
        lst : array of ints, shape (6n-12,)
            nodal indices with lptr and lend, define the triangulation as a set of N
            adjacency lists; counterclockwise-ordered sequences of neighboring nodes
            such that the first and last neighbors of a boundary node are boundary
            nodes (the first neighbor of an interior node is arbitrary).  In order to
            distinguish between interior and boundary nodes, the last neighbor of
            each boundary node is represented by the negative of its index.
            The indices are 1-based (as in Fortran), not zero based (as in python).
        lptr : array of ints, shape (6n-12),)
            set of pointers in one-to-one correspondence with the elements of lst.
            lst(lptr(i)) indexes the node which follows lst(i) in cyclical
            counterclockwise order (the first neighbor follows the last neighbor).
            The indices are 1-based (as in Fortran), not zero based (as in python).
        lend : array of ints, shape (n,)
            N pointers to adjacency lists.
            lend(k) points to the last neighbor of node K.
            lst(lend(K)) < 0 if and only if K is a boundary node.
            The indices are 1-based (as in Fortran), not zero based (as in python).

    Notes:
        Provided the nodes are randomly ordered, the algorithm
        has expected time complexity \\(O(N \\log (N)\\) for most nodal
        distributions.  Note, however, that the complexity may be
        as high as \\(O(N^2)\\) if, for example, the nodes are ordered
        on increasing x.

        If `permute=True`, x and y are randomised on input before
        they are triangulated. The distribution of triangles will
        differ between setting `permute=True` and `permute=False`,
        however, the node ordering will remain identical.
    """
    def __init__(self, x, y, refinement_levels=0, permute=False, tree=False):

        self.permute = permute
        self.tree = tree

        self._update_triangulation(x, y)

        for r in range(0,refinement_levels):
            x, y = self.uniformly_refine_triangulation(faces=False, trisect=False)
            self._update_triangulation(x, y)

        return


    def _generate_permutation(self, npoints):
        i = np.arange(0, npoints)
        p = np.random.permutation(npoints)
        ip = np.empty_like(p)
        ip[p[i]] = i
        return p, ip

    def _is_collinear(self, x, y):
        """
        Checks if first three points are collinear
        """
        pts = np.column_stack([x[:3], y[:3], np.ones(3)])
        return np.linalg.det(pts) == 0.0


    def _update_triangulation(self, x, y):

        npoints = len(x)

        # Deal with collinear issue

        if self.permute:
            niter = 0
            ierr = -2
            while ierr == -2 and niter < 5:
                p, ip = self._generate_permutation(npoints)
                x = x[p]
                y = y[p]
                lst, lptr, lend, ierr = _tripack.trmesh(x, y)
                niter += 1

            if niter >= 5:
                raise ValueError(_ier_codes[-2])
        else:
            p = np.arange(0, npoints)
            ip = p
            lst, lptr, lend, ierr = _tripack.trmesh(x, y)


        self._permutation = p
        self._invpermutation = ip


        if ierr > 0:
            raise ValueError('ierr={} in trmesh\n{}'.format(ierr, _ier_codes[9999]))
        elif ierr != 0:
            raise ValueError('ierr={} in trmesh\n{}'.format(ierr, _ier_codes[ierr]))

        self.npoints = npoints
        self._x = x
        self._y = y
        self._points = np.column_stack([x, y])
        self.lst = lst
        self.lptr = lptr
        self.lend = lend

        # Convert a triangulation to a triangle list form (human readable)
        # Uses an optimised version of trlist that returns triangles
        # without neighbours or arc indices
        nt, ltri, ierr = _tripack.trlist2(lst, lptr, lend)

        if ierr != 0:
            raise ValueError('ierr={} in trlist2\n{}'.format(ierr, _ier_codes[ierr]))

        # extract triangle list and convert to zero-based ordering
        self._simplices = ltri.T[:nt] - 1
        area = self.areas()
        self._simplices = self._simplices[area > 0.0]

        ## If scipy is installed, build a KDtree to find neighbour points

        if self.tree:
            self._build_cKDtree()

        return

    # Define properties on each attribute to return correct ordering
    # when called

    @property
    def x(self):
        """ Stored Cartesian x coordinates from triangulation """
        return self._deshuffle_field(self._x)
    @property
    def y(self):
        """ Stored Cartesian y coordinates from triangulation """
        return self._deshuffle_field(self._y)
    @property
    def points(self):
        """ Stored Cartesian xy coordinates from triangulation """
        return self._deshuffle_field(self._points)
    @property
    def simplices(self):
        """ Indices of the points forming the simplices in the triangulation.
        Points are ordered anticlockwise """
        return self._deshuffle_simplices(self._simplices)


    def _shuffle_field(self, *args):
        """
        Permute field
        """

        p = self._permutation

        fields = []
        for arg in args:
            fields.append( arg[p] )

        if len(fields) == 1:
            return fields[0]
        else:
            return fields

    def _deshuffle_field(self, *args):
        """
        Return to original ordering
        """

        ip = self._invpermutation

        fields = []
        for arg in args:
            fields.append( arg[ip] )

        if len(fields) == 1:
            return fields[0]
        else:
            return fields

    def _deshuffle_simplices(self, simplices):
        """
        Return to original ordering
        """
        p = self._permutation
        return p[simplices]


    def gradient(self, f, nit=3, tol=1e-3, guarantee_convergence=False):
        """
        Return the gradient of an n-dimensional array.

        The method consists of minimizing a quadratic functional Q(G) over
        gradient vectors (in x and y directions), where Q is an approximation
        to the linearized curvature over the triangulation of a C-1 bivariate
        function \\(F(x,y)\\) which interpolates the nodal values and gradients.

        Args:
            f : array of floats, shape (n,)
                field over which to evaluate the gradient
            nit : int (default: 3)
                number of iterations to reach a convergence tolerance,
                tol nit >= 1
            tol: float (default: 1e-3)
                maximum change in gradient between iterations.
                convergence is reached when this condition is met.

        Returns:
            dfdx : array of floats, shape (n,)
                derivative of f in the x direction
            dfdy : array of floats, shape (n,)
                derivative of f in the y direction

        Notes:
            For SIGMA = 0, optimal efficiency was achieved in testing with
            tol = 0, and nit = 3 or 4.

            The restriction of F to an arc of the triangulation is taken to be
            the Hermite interpolatory tension spline defined by the data values
            and tangential gradient components at the endpoints of the arc, and
            Q is the sum over the triangulation arcs, excluding interior
            constraint arcs, of the linearized curvatures of F along the arcs --
            the integrals over the arcs of \\( (d^2 F / dT^2)^2\\), where \\( d^2 F / dT^2\\)is the second
            derivative of \\(F\\) with respect to distance \\(T\\) along the arc.
        """
        if f.size != self.npoints:
            raise ValueError('f should be the same size as mesh')

        gradient = np.zeros((2,self.npoints), order='F', dtype=np.float32)
        sigma = 0
        iflgs = 0

        f = self._shuffle_field(f)

        ierr = 1
        while ierr == 1:
            ierr = _srfpack.gradg(self._x, self._y, f, self.lst, self.lptr, self.lend,\
                                  iflgs, sigma, gradient, nit=nit, dgmax=tol)
            if not guarantee_convergence:
                break

        if ierr < 0:
            raise ValueError('ierr={} in gradg\n{}'.format(ierr, _ier_codes[ierr]))

        return self._deshuffle_field(gradient[0], gradient[1])


    def gradient_local(self, f, index):
        """
        Return the gradient at a specified node.

        This routine employs a local method, in which values depend only on nearby
        data points, to compute an estimated gradient at a node.

        `gradient_local()` is more efficient than `gradient()` only if it is unnecessary
        to compute gradients at all of the nodes. Both routines have similar accuracy.
        """
        if f.size != self.npoints:
            raise ValueError('f should be the same size as mesh')

        f = self._shuffle_field(f)


        gradX, gradY, l = _srfpack.gradl(index + 1, self._x, self._y, f,\
                                         self.lst, self.lptr, self.lend)

        return gradX, gradY


    def smoothing(self, f, w, sm, smtol, gstol):
        r"""
        Smooths a surface `f` by choosing nodal function values and gradients to
        minimize the linearized curvature of F subject to a bound on the
        deviation from the data values. This is more appropriate than interpolation
        when significant errors are present in the data.

        Args:
            f : array of floats, shape (n,)
                field to apply smoothing on
            w : array of floats, shape (n,)
                weights associated with data value in `f`
                `w[i] = 1/sigma_f**2` is a good rule of thumb.
            sm : float
                positive parameter specifying an upper bound on Q2(f).
                generally `n-sqrt(2n) <= sm <= n+sqrt(2n)`
            smtol : float [0,1]
                specifies relative error in satisfying the constraint
                `sm(1-smtol) <= Q2 <= sm(1+smtol)` between 0 and 1.
            gstol : float
                tolerance for convergence.
                `gstol = 0.05*mean(sigma_f)**2` is a good rule of thumb.

        Returns:
            f_smooth : array of floats, shape (n,)
                smoothed version of f
            derivatives : tuple of floats, shape (n,3)
                \\( \partial f \partial y , \partial f \partial y \\) first derivatives
                of `f_smooth` in the x and y directions
            err : error indicator
                0 indicates no error, +ve values indicate warnings, -ve values are errors

        """
        if f.size != self.npoints or f.size != w.size:
            raise ValueError('f and w should be the same size as mesh')

        f, w = self._shuffle_field(f, w)

        sigma = 0
        iflgs = 0

        f_smooth, df, ierr = _srfpack.smsurf(self.x, self.y, f, self.lst, self.lptr, self.lend,\
                                             iflgs, sigma, w, sm, smtol, gstol)

        import warnings

        # Note - warnings are good because they can be 'upgraded' to exceptions by the
        # user of the module. The warning text is usually something that we don't
        # emit every time the error occurs. So here we emit a message about the problem
        # and a warning that explains it (once) - and also serves as a hook for an exception trap.


        if ierr < 0:
            raise ValueError('ierr={} in gradg\n{}'.format(ierr, _ier_codes[ierr]))
        if ierr == 1:
            warnings.warn("No errors were encountered but the constraint is not active --\n\
                  F, FX, and FY are the values and partials of a linear function \
                  which minimizes Q2(F), and Q1 = 0.")

        return self._deshuffle_field(f_smooth), self._deshuffle_field(df[0], df[1]), ierr


    def interpolate(self, xi, yi, zdata, order=1):
        """
        Base class to handle nearest neighbour, linear, and cubic interpolation.
        Given a triangulation of a set of nodes and values at the nodes,
        this method interpolates the value at the given xi,yi coordinates.

        Args:
            xi : float / array of floats, shape (l,)
                x Cartesian coordinate(s)
            yi : float / array of floats, shape (l,)
                y Cartesian coordinate(s)
            zdata : array of floats, shape (n,)
                value at each point in the triangulation
                must be the same size of the mesh
            order : int (default=1)
                order of the interpolatory function used:
                    0 = nearest-neighbour,
                    1 = linear,
                    3 = cubic

        Returns:
            zi : float / array of floats, shape (l,)
                interpolates value(s) at (xi, yi)
            err : int / array of ints, shape (l,)
                whether interpolation (0), extrapolation (1) or error (other)
        """

        if order == 0:
            return self.interpolate_nearest(xi, yi, zdata)
        elif order == 1:
            return self.interpolate_linear(xi, yi, zdata)
        elif order == 3:
            return self.interpolate_cubic(xi, yi, zdata)
        else:
            raise ValueError("order must be 0, 1, or 3")


    def interpolate_nearest(self, xi, yi, zdata):
        """
        Nearest-neighbour interpolation.
        Calls nearnd to find the index of the closest neighbours to xi,yi

        Args:
            xi : float / array of floats, shape (l,)
                x coordinates on the Cartesian plane
            yi : float / array of floats, shape (l,)
                y coordinates on the Cartesian plane

        Returns:
            zi : float / array of floats, shape (l,)
                nearest-neighbour interpolated value(s) of (xi,yi)
            err : int / array of ints, shape (l,)
                whether interpolation (0), extrapolation (1) or error (other)
        """
        if zdata.size != self.npoints:
            raise ValueError('zdata should be same size as mesh')

        xi = np.atleast_1d(xi)
        yi = np.atleast_1d(yi)

        size = xi.size

        zdata = self._shuffle_field(zdata)

        zierr = np.zeros(size, dtype=np.int32)
        ist = np.ones(size, dtype=np.int32)
        ist, dist = _tripack.nearnds(xi, yi, ist, self._x, self._y,
                                     self.lst, self.lptr, self.lend)

        # check if interpolation or extrapolation
        hull_idx = self.convex_hull()
        hull_pts = self.points[hull_idx]
        hull_x = hull_pts[:,0]
        hull_y = hull_pts[:,1]

        for i in range(0, zierr.size):
            vector_det = (hull_x[1:] - hull_x[:-1])*(yi[i] - hull_y[:-1]) - \
                         (hull_y[1:] - hull_y[:-1])*(xi[i] - hull_x[:-1])

            # if vector_det > 0: within convex hull
            # if vector_det = 0: on top of convex hull
            # if vector_det < 0: outside convex hull
            zierr[i] = (vector_det < 0).any()

        return np.squeeze(zdata[ist - 1]), zierr


    def interpolate_linear(self, xi, yi, zdata):
        """
        Piecewise linear interpolation / extrapolation to arbitrary point(s).
        The method is fast, but has only \\(C^0\\) continuity.

        Args:
            xi : float / array of floats, shape (l,)
                x coordinates on the Cartesian plane
            yi : float / array of floats, shape (l,)
                y coordinates on the Cartesian plane
            zdata : array of floats, shape (n,)
                value at each point in the triangulation
                must be the same size of the mesh

        Returns:
            zi : float / array of floats, shape (l,)
                interpolated value(s) of (xi,yi)
            err : int / array of ints, shape (l,)
                whether interpolation (0), extrapolation (1) or error (other)
        """

        if zdata.size != self.npoints:
            raise ValueError('zdata should be same size as mesh')

        xi = np.atleast_1d(xi)
        yi = np.atleast_1d(yi)

        size = xi.size

        zi = np.empty(size)
        zierr = np.empty(size, dtype=np.int)

        zdata = self._shuffle_field(zdata)

        # iterate
        for i in range(0, size):
            ist = np.abs(self._x - xi[i]).argmin() + 1
            zi[i], zierr[i] = _srfpack.intrc0(xi[i], yi[i], self._x, self._y, zdata,\
                                       self.lst, self.lptr, self.lend, ist)

        return np.squeeze(zi), zierr


    def interpolate_cubic(self, xi, yi, zdata, gradz=None, derivatives=False):
        """
        Cubic spline interpolation / extrapolation to arbirary point(s).
        This method has \\(C^1\\) continuity.

        Args:
            xi : float / array of floats, shape (l,)
                x coordinates on the Cartesian plane
            yi : float / array of floats, shape (l,)
                y coordinates on the Cartesian plane
            zdata : array of floats, shape (n,)
                value at each point in the triangulation
                must be the same size of the mesh
            gradz : array of floats, shape (2,n) (optional)
                derivative at each point in the triangulation in the
                - x-direction (first row),
                - y-direction (second row)
                if not supplied it is evaluated using `gradient()`
            derivatives : bool (default=False)
                optionally returns \\( \\frac{df}{dx} , \\frac{df}{dy} \\)
                the first derivatives at point(s) (xi,yi)

        Returns:
            zi : float / array of floats, shape (l,)
                interpolated value(s) of (xi,yi)
            err : int / array of ints, shape (l,)
                whether interpolation (0), extrapolation (1) or error (other)
            dzx, dzy (optional) : float, array of floats, shape(l,)
                first partial derivatives \\( \\partial f \\partial x , \\partial f \\partial y \\)
                at (xi,yi)
        """

        if zdata.size != self.npoints:
            raise ValueError('zdata should be same size as mesh')

        if type(gradz) == type(None):
            gradX, gradY = self.gradient(zdata)
            gradX, gradY = self._shuffle_field(gradX, gradY)
        elif np.array(gradz).shape == (2,self.npoints):
            gradX, gradY = self._shuffle_field(gradz[0], gradz[1])
        else:
            raise ValueError("gradz must be of shape {}".format((2,self.npoints)))

        iflgs = 0
        dflag = 1
        sigma = 0.0


        xi = np.atleast_1d(xi)
        yi = np.atleast_1d(yi)

        size = xi.size

        zi = np.empty(size)
        dzx = np.empty(size)
        dzy = np.empty(size)
        zierr = np.empty(size, dtype=np.int)

        gradZ = np.vstack([gradX, gradY])
        zdata = self._shuffle_field(zdata)

        for i in range(0, size):
            ist = np.abs(self._x - xi[i]).argmin() + 1
            zi[i], dzx[i], dzy[i], zierr[i] = _srfpack.intrc1(xi[i], yi[i], self._x, self._y, zdata,\
                               self.lst, self.lptr, self.lend, iflgs, sigma, gradZ, dflag, ist)

        if derivatives:
            return np.squeeze(zi), zierr, (dzx, dzy)
        else:
            return np.squeeze(zi), zierr


    def neighbour_simplices(self):
        """
        Get indices of neighbour simplices for each simplex.
        The kth neighbour is opposite to the kth vertex.
        For simplices at the boundary, -1 denotes no neighbour.
        """
        nt, ltri, lct, ierr = _tripack.trlist(self.lst, self.lptr, self.lend, nrow=6)
        if ierr != 0:
            raise ValueError('ierr={} in trlist\n{}'.format(ierr, _ier_codes[ierr]))
        return ltri.T[:nt,3:] - 1


    def neighbour_and_arc_simplices(self):
        """
        Get indices of neighbour simplices for each simplex and arc indices.
        Identical to get_neighbour_simplices() but also returns an array
        of indices that reside on boundary hull, -1 denotes no neighbour.
        """
        nt, ltri, lct, ierr = _tripack.trlist(self.lst, self.lptr, self.lend, nrow=9)
        if ierr != 0:
            raise ValueError('ierr={} in trlist\n{}'.format(ierr, _ier_codes[ierr]))
        ltri = ltri.T[:nt] - 1
        return ltri[:,3:6], ltri[:,6:]


    def nearest_vertex(self, xi, yi):
        """
        Locate the index of the nearest vertex to points (xi,yi)
        and return the squared distance between (xi,yi) and
        each nearest neighbour.

        Args:
            xi : array of floats, shape (l,)
                Cartesian coordinates in the x direction
            yi : array of floats, shape (l,)
                Cartesian coordinates in the y direction

        Returns:
            index : array of ints
                the nearest vertex to each of the supplied points
            dist : array of floats
                squared distance to the closest vertex identified

        Notes:
            Faster searches can be obtained using a KDTree.
            Store all x and y coordinates in a (c)KDTree, then query
            a set of points to find their nearest neighbours.
        """
        n = np.array(xi).size
        xi = np.array(xi).reshape(n)
        yi = np.array(yi).reshape(n)

        idx  = np.empty_like(xi, dtype=np.int)
        dist = np.empty_like(xi, dtype=np.float)

        for pt in range(0, n):
            # i is the node at which we start the search
            # the closest x coordinate is a good place
            i = np.abs(self._x - xi[pt]).argmin()

            idx[pt], dist[pt] = _tripack.nearnd(xi[pt], yi[pt], i, self._x, self._y,\
                                                self.lst, self.lptr, self.lend)
        idx -= 1 # return to C ordering

        return self._deshuffle_simplices(idx), dist


    def containing_triangle(self, xi, yi):
        """
        Returns indices of the triangles containing xi yi

        Args:
            xi : float / array of floats, shape (l,)
                Cartesian coordinates in the x direction
            yi : float / array of floats, shape (l,)
                Cartesian coordinates in the y direction

        Returns:
            tri_indices: array of ints, shape (l,)

        Notes:
            The simplices are found as `cartesian.Triangulation.simplices[tri_indices]`
        """
        p = self._permutation
        pts = np.column_stack([xi, yi])

        sorted_simplices = np.sort(self._simplices, axis=1)

        triangles = []
        for pt in pts:
            t = _tripack.trfind(3, pt[0], pt[1], self._x, self._y, self.lst, self.lptr, self.lend)
            tri = np.sort(t) - 1

            triangles.extend(np.where(np.all(p[sorted_simplices]==p[tri], axis=1))[0])

        return np.array(triangles).ravel()


    def containing_simplex_and_bcc(self, xi, yi):
        """
        Returns the simplices containing (xi,yi)
        and the local barycentric, normalised coordinates.

        Args:
            xi : float / array of floats, shape (l,)
               Cartesian coordinates in the x direction
            yi : float / array of floats, shape (l,)
               Cartesian coordinates in the y direction

        Returns:
            bcc : normalised barycentric coordinates
            tri : simplices containing (xi,yi)

        Notes:
            The ordering of the vertices may differ from that stored in
            `self.simplices` array but will still be a loop around the simplex.
        """

        pts = np.column_stack([xi,yi])

        tri = np.empty((pts.shape[0], 3), dtype=np.int) # simplices
        bcc = np.empty_like(tri, dtype=np.float) # barycentric coords

        for i, pt in enumerate(pts):
            t = _tripack.trfind(3, pt[0], pt[1], self._x, self._y, self.lst, self.lptr, self.lend)
            tri[i] = t

            vert = self._points[tri[i] - 1]
            v0 = vert[1] - vert[0]
            v1 = vert[2] - vert[0]
            v2 = pt - vert[0]

            d00 = v0.dot(v0)
            d01 = v0.dot(v1)
            d11 = v1.dot(v1)
            d20 = v2.dot(v0)
            d21 = v2.dot(v1)
            denom = d00*d11 - d01*d01

            v = (d11 * d20 - d01 * d21) / denom
            w = (d00 * d21 - d01 * d20) / denom
            u = 1.0 - v - w

            bcc[i] = [u, v, w]

        tri -= 1 # return to C ordering

        bcc /= bcc.sum(axis=1).reshape(-1,1)

        return bcc, self._deshuffle_simplices(tri)


    def identify_vertex_neighbours(self, vertex):
        """
        Find the neighbour-vertices in the triangulation for the given vertex
        Searches `self.simplices` for vertex entries and sorts neighbours
        """
        simplices = self.simplices
        ridx, cidx = np.where(simplices == vertex)
        neighbour_array = np.unique(np.hstack([simplices[ridx]])).tolist()
        neighbour_array.remove(vertex)
        return neighbour_array



    def identify_vertex_triangles(self, vertices):
        """
        Find all triangles which own any of the vertices in the list provided
        """

        triangles = []

        for vertex in np.array(vertices).reshape(-1):
            triangles.append(np.where(self.simplices == vertex)[0])

        return np.unique(np.concatenate(triangles))


    def identify_segments(self):
        """
        Find all the segments in the triangulation and return an
        array of vertices (n1,n2) where n1 < n2
        """

        i1 = np.sort([self._simplices[:,0], self._simplices[:,1]], axis=0)
        i2 = np.sort([self._simplices[:,0], self._simplices[:,2]], axis=0)
        i3 = np.sort([self._simplices[:,1], self._simplices[:,2]], axis=0)

        a = np.hstack([i1, i2, i3]).T

        # find unique rows in numpy array
        # <http://stackoverflow.com/questions/16970982/find-unique-rows-in-numpy-array>
        b = np.ascontiguousarray(a).view(np.dtype((np.void, a.dtype.itemsize * a.shape[1])))
        segments = np.unique(b).view(a.dtype).reshape(-1, a.shape[1])

        return self._deshuffle_simplices(segments)


    def segment_midpoints_by_vertices(self, vertices):
        """
        Add midpoints to any segment connected to the vertices in the
        list / array provided.
        """

        segments = set()

        for vertex in vertices:
            neighbours = self.identify_vertex_neighbours(vertex)
            segments.update( min( tuple((vertex, n1)), tuple((n1, vertex))) for n1 in neighbours )

        segs = np.array(list(segments))

        new_midpoints = self.segment_midpoints(segments=segs)

        return new_midpoints


    def face_midpoints(self, simplices=None):
        """
        Identify the centroid of every simplex in the triangulation. If an array of
        simplices is given then the centroids of only those simplices is returned.
        """

        if type(simplices) == type(None):
            simplices = self.simplices

        mids = self.points[simplices].mean(axis=1)
        mid_xpt, mid_ypt = mids[:,0], mids[:,1]

        return mid_xpt, mid_ypt


    def segment_midpoints(self, segments=None):
        """
        Identify the midpoints of every line segment in the triangulation.
        If an array of segments of shape (no_of_segments,2) is given,
        then the midpoints of only those segments is returned.

        Notes:
            Segments in the array must not be duplicates or the re-triangulation
            will fail. Take care not to miss that (n1,n2) is equivalent to (n2,n1).
        """

        if type(segments) == type(None):
            segments = self.identify_segments()
        points = self.points

        mids = (points[segments[:,0]] + points[segments[:,1]]) * 0.5
        mid_xpt, mid_ypt = mids[:,0], mids[:,1]

        return mid_xpt, mid_ypt


    def segment_tripoints(self, ratio=0.33333):
        """
        Identify the trisection points of every line segment in the triangulation
        """

        segments = self.identify_segments()
        points = self.points

        mids1 = ratio*points[segments[:,0]] + (1.0-ratio)*points[segments[:,1]]
        mids2 = (1.0-ratio)*points[segments[:,0]] + ratio*points[segments[:,1]]

        mids = np.vstack((mids1,mids2))
        mid_xpt, mid_ypt = mids[:,0], mids[:,1]

        return mid_xpt, mid_ypt


    def convex_hull(self):
        """
        Find the Convex Hull of the internal set of x,y points.

        Returns:
            bnodes : array of ints
                indices corresponding to points on the convex hull
        """
        bnodes, nb, na, nt = _tripack.bnodes(self.lst, self.lptr, self.lend, self.npoints)
        return self._deshuffle_simplices(bnodes[:nb] - 1)


    def areas(self):
        """
        Compute the area of each triangle within the triangulation of points.

        Returns:
            area : array of floats, shape (nt,)
                area of each triangle in `self.simplices` where nt
                is the number of triangles.

        """
        v1 = self.points[self.simplices[:,1]] - self.points[self.simplices[:,0]]
        v2 = self.points[self.simplices[:,2]] - self.points[self.simplices[:,1]]

        area = 0.5*(v1[:,0]*v2[:,1] - v1[:,1]*v2[:,0])
        return area


    def edge_lengths(self):
        """
        Compute the edge-lengths of each triangle in the triangulation.
        """
        simplex = self.simplices.T

        # simplex is vectors a, b, c defining the corners
        a = self.points[simplex[0]]
        b = self.points[simplex[1]]
        c = self.points[simplex[2]]

        # norm to calculate length
        ab = np.linalg.norm(b - a, axis=1)
        bc = np.linalg.norm(c - a, axis=1)
        ac = np.linalg.norm(a - c, axis=1)

        return ab, bc, ac


    def _add_midpoints(self):

        mid_xpt, mid_ypt = self.segment_midpoints()

        x_v2 = np.concatenate([self.x, mid_xpt], axis=0)
        y_v2 = np.concatenate([self.y, mid_ypt], axis=0)

        return x_v2, y_v2

    def _add_tripoints(self, ratio=0.333333):

        mid_xpt, mid_ypt = self.segment_tripoints()

        x_v2 = np.concatenate([self.x, mid_xpt], axis=0)
        y_v2 = np.concatenate([self.y, mid_ypt], axis=0)

        return x_v2, y_v2

    def _add_face_centroids(self):

        face_xpt, face_ypt = self.face_midpoints()

        x_v2 = np.concatenate((self.x, face_xpt), axis=0)
        y_v2 = np.concatenate((self.y, face_ypt), axis=0)

        return x_v2, y_v2


    def uniformly_refine_triangulation(self, faces=False, trisect=False):
        """
        return points defining a refined triangulation obtained by bisection of all edges
        in the triangulation
        """

        if faces:
            x_v1, y_v1 = self._add_face_centroids()

        else:
            if not trisect:
                x_v1, y_v1 = self._add_midpoints()
            else:
                x_v1, y_v1 = self._add_tripoints(ratio=0.333333)

        return x_v1, y_v1


    def midpoint_refine_triangulation_by_vertices(self, vertices):
        """
        return points defining a refined triangulation obtained by bisection of all edges
        in the triangulation connected to any of the vertices in the list provided
        """

        xi, yi = self.segment_midpoints_by_vertices(vertices=vertices)

        x_v1 = np.concatenate((self.x, xi), axis=0)
        y_v1 = np.concatenate((self.y, yi), axis=0)

        return x_v1, y_v1


    def edge_refine_triangulation_by_triangles(self, triangles):
        """
        return points defining a refined triangulation obtained by bisection of all edges
        in the triangulation that are associated with the triangles in the list
        of indices provided.

        Notes:
            The triangles are here represented as a single index.
            The vertices of triangle `i` are given by `self.simplices[i]`.
        """

        ## Note there should be no duplicates in the list of triangles
        ## but because we remove duplicates from the list of all segments,
        ## there is no pressing need to check this.

        # identify the segments

        simplices = self.simplices
        segments = set()

        for index in np.array(triangles).reshape(-1):
            tri = simplices[index]
            segments.add( min( tuple((tri[0], tri[1])), tuple((tri[0], tri[1]))) )
            segments.add( min( tuple((tri[1], tri[2])), tuple((tri[2], tri[1]))) )
            segments.add( min( tuple((tri[0], tri[2])), tuple((tri[2], tri[0]))) )

        segs = np.array(list(segments))

        xi, yi = self.segment_midpoints(segs)

        x_v1 = np.concatenate((self.x, xi), axis=0)
        y_v1 = np.concatenate((self.y, yi), axis=0)

        return x_v1, y_v1


    def edge_refine_triangulation_by_vertices(self, vertices):
        """
        return points defining a refined triangulation obtained by bisection of all edges
        in the triangulation connected to any of the vertices in the list provided
        """

        triangles = self.identify_vertex_triangles(vertices)

        return self.edge_refine_triangulation_by_triangles(triangles)


    def centroid_refine_triangulation_by_triangles(self, triangles):
        """
        return points defining a refined triangulation obtained by bisection of all edges
        in the triangulation that are associated with the triangles in the list provided.

        Notes:
            The triangles are here represented as a single index.
            The vertices of triangle `i` are given by `self.simplices[i]`.
        """

        # Remove duplicates from the list of triangles

        triangles = np.unique(np.array(triangles))

        xi, yi = self.face_midpoints(simplices=self.simplices[triangles])

        x_v1 = np.concatenate((self.x, xi), axis=0)
        y_v1 = np.concatenate((self.y, yi), axis=0)

        return x_v1, y_v1


    def centroid_refine_triangulation_by_vertices(self, vertices):
        """
        return points defining a refined triangulation obtained by bisection of all edges
        in the triangulation connected to any of the vertices in the list provided
        """

        triangles = self.identify_vertex_triangles(vertices)

        return self.centroid_refine_triangulation_by_triangles(triangles)


    def join(self, t2, unique=False):
        """
        Join this triangulation with another. If the points are known to have no duplicates, then
        set unique=False to skip the testing and duplicate removal
        """

        x_v1 = np.concatenate((self.x, t2.x), axis=0)
        y_v1 = np.concatenate((self.y, t2.y), axis=0)

        ## remove any duplicates

        if not unique:
            a = np.ascontiguousarray(np.vstack((x_v1, y_v1)).T)
            unique_a = np.unique(a.view([('', a.dtype)]*a.shape[1]))
            unique_coords = unique_a.view(a.dtype).reshape((unique_a.shape[0], a.shape[1]))

            x_v1 = unique_coords[:,0]
            y_v1 = unique_coords[:,1]

        return x_v1, y_v1


    def _build_cKDtree(self):

        try:
            import scipy.spatial
            self._cKDtree = scipy.spatial.cKDTree(self.points)

        except:
            self._cKDtree = None


    def nearest_vertices(self, x, y, k=1, max_distance=np.inf ):
        """
        Query the cKDtree for the nearest neighbours and Euclidean
        distance from x,y points.

        Returns 0, 0 if a cKDtree has not been constructed
        (switch `tree=True` if you need this routine)

        Args:
            x : 1D array of Cartesian x coordinates
            y : 1D array of Cartesian y coordinates
            k : int (defaul=1)
                number of nearest neighbours to return
            max_distance : float (default: inf)
                maximum Euclidean distance to search for neighbours

        Returns:
            d : array of floats
                Euclidean distance between each point and their
                nearest neighbour(s)
            vert : array of ints
                vertices of the nearest neighbour(s)
        """

        if self.tree == False or self.tree == None:
            return 0, 0

        xy = np.column_stack([x, y])

        dxy, vertices = self._cKDtree.query(xy, k=k, distance_upper_bound=max_distance)


        if k == 1:   # force this to be a 2D array
            vertices = np.reshape(vertices, (-1, 1))

        return dxy, vertices


def remove_duplicates(vector_tuple):
    """
    Remove duplicates rows from N equally-sized arrays
    """
    array = np.column_stack(vector_tuple)
    a = np.ascontiguousarray(array)
    unique_a = np.unique(a.view([('', a.dtype)]*a.shape[1]))
    b = unique_a.view(a.dtype).reshape((unique_a.shape[0], a.shape[1]))
    return list(b.T)
